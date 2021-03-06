from __future__ import absolute_import
from __future__ import division
from __future__ import print_function

import sys
import time

import numpy as np
import torch
import torch.optim as optimize

from transition.data.phrase_tree import PhraseTree
from transition.inference.parser import Parser
from transition.models.parser.features import FeatureMapper
from transition.models.parser.network import Network
from transition.utils.measures import FScore
from transition.utils.global_names import GlobalNames

def generate_vocab(args):
    if args.vocab is not None:
        fm = FeatureMapper.load_json(args.vocab)
    elif args.train is not None:
        fm = FeatureMapper(args.train)
        if args.vocab_output is not None:
            fm.save_json(args.vocab_output)
            print('Wrote vocabulary file {}'.format(args.vocab_output))
            sys.exit()
    else:
        print('Must specify either --vocab-file or --train-data.')
        print('    (Use -h or --help flag for full option list.)')
        sys.exit()
    return fm


def test(fm, args):
    test_trees = PhraseTree.load_trees(args.test)
    print('Loaded test trees from {}'.format(args.test))
    network = torch.load(args.model)
    print('Loaded model from: {}'.format(args.model))
    accuracy = Parser.evaluate_corpus(test_trees, fm, network)
    print('Accuracy: {}'.format(accuracy))


def train(fm, args):
    train_data_file = args.train
    dev_data_file = args.dev
    epochs = args.epochs
    batch_size = args.batch_size
    unk_param = args.unk_param
    alpha = args.alpha
    beta = args.beta
    model_save_file = args.model

    print("this is train mode")
    start_time = time.time()

    network = Network(fm, args)
    optimizer = optimize.Adadelta(network.parameters(), eps=1e-7, rho=0.99)

    # network.cuda()

    training_data = fm.gold_data_from_file(train_data_file)
    num_batches = -(-len(training_data) // batch_size)
    print('Loaded {} training sentences ({} batches of size {})!'.format(
        len(training_data),
        num_batches,
        batch_size,
    ))
    parse_every = -(-num_batches // 4)

    dev_trees = PhraseTree.load_trees(dev_data_file)
    print('Loaded {} validation trees!'.format(len(dev_trees)))

    best_acc = FScore()

    for epoch in xrange(1, epochs + 1):
        print('........... epoch {} ...........'.format(epoch))

        total_cost = 0.0
        total_states = 0
        training_acc = FScore()

        np.random.shuffle(training_data)

        for b in xrange(num_batches):
            network.zero_grad()
            batch = training_data[(b * batch_size): ((b + 1) * batch_size)]
            batch_loss = None
            for example in batch:
                example_Loss, example_states, acc = Parser.exploration(example, fm, network, alpha, beta, unk_param)
                total_states += example_states
                if batch_loss is not None:
                    batch_loss += example_Loss
                else:
                    batch_loss = example_Loss
                training_acc += acc
            if GlobalNames.use_gpu:
                total_cost += batch_loss.cpu().data.numpy()[0]
            else:
                total_cost += batch_loss.data.numpy()[0]
            batch_loss.backward()
            optimizer.step()

            mean_cost = total_cost / total_states

            print(
                '\rBatch {}  Mean Cost {:.4f} [Train: {}]'.format(
                    b,
                    mean_cost,
                    training_acc,
                ),
                end='',
            )
            sys.stdout.flush()

            if ((b + 1) % parse_every) == 0 or b == (num_batches - 1):
                dev_acc = Parser.evaluate_corpus(
                    dev_trees,
                    fm,
                    network,
                )
                print(' [Dev: {}]'.format(dev_acc))

                if dev_acc > best_acc:
                    best_acc = dev_acc
                    torch.save(network, model_save_file)
                    print(' [saved model: {}]'.format(model_save_file))

        current_time = time.time()
        runmins = (current_time - start_time) / 60.
        print('  Elapsed time: {:.2f}m'.format(runmins))
