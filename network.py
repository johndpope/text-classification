import sys
import time
from collections import Counter
import tensorflow as tf
import numpy as np

import pymysql
from tflearn.data_utils import VocabularyProcessor

from utils import create_lookup_tables

local_db_connection = pymysql.connect(host='localhost', database='edusson', user='root', password='')
db_cursor_read = local_db_connection.cursor()

counter = Counter()
X_train = []
Y_train = []
X_test = []
Y_test = []
vocab_to_int = {}
int_to_vocab = {}
max_sentence_length = 500

def preprocess():
    db_cursor_read.execute('SELECT * FROM prepared_orders ORDER BY rand()')
    for row in db_cursor_read: preprocess_row(row)
    #db_cursor_read.execute("SELECT max(name_words), max(description_words) FROM prepared_orders")
    #max_name_words, max_description_words = db_cursor_read.fetchone()
    create_neural_network()


def preprocess_row(row):
    global X_train, Y_train

    DB_STATUS_INDEX = 1
    DB_TITLE_INDEX = 5
    DB_DESCRIPTION_INDEX = 6

    state = row[DB_STATUS_INDEX]
    title_words = row[DB_TITLE_INDEX].split(' ')
    description_words = row[DB_DESCRIPTION_INDEX].split(' ')

    if state not in [3, 4, 5, 6, 9, 11]:
        return

    # for word in title_words:
    #     add_word(word)

    x = []

    for word in description_words[:max_sentence_length]:
        word = prepare_word(word)
        add_word(word)
        x.append(word)

    X_train.append([' '.join(x)])
    y = int(state in [3])
    Y_train.append([y, 1 - y])

# '1', 'Bidding', NULL, '1'
# '2', 'In Progress', NULL, '1'
# '3', 'Finished', NULL, '1'
# '4', 'Canceled by Customer', NULL, '1'
# '5', 'Canceled by Writer', NULL, '1'
# '6', 'Canceled by System', NULL, '1'
# '9', 'Not Active', NULL, '2'
# '10', 'Active', NULL, '2'
# '11', 'Expired', NULL, '2'
# '12', 'Pending Payment', NULL, '1'
# '13', 'Under Investigation', NULL, '1'
# '14', 'Pending Writer', NULL, '1'

def prepare_word(word):
    word = word.strip("'")
    return word

def add_word(word):
    global counter
    counter[word] = counter.get(word, 0) + 1

def preprocess_data():
    global X_train, Y_train, X_test, Y_test

    #vocab_processor = VocabularyProcessor(max_document_length=max_sentence_length, vocabulary=vocab_to_int)
    for row in range(len(X_train)):
        encoded = string_to_vocab(X_train[row][0], max_sentence_length)
        X_train[row] = encoded
        #X_train[row] = list(vocab_processor.transform(X_train[row]))
        #print(X_train[row])

    test_data_size = 5000
    X_test = np.array(X_train[:test_data_size], dtype=np.int32)
    Y_test = np.array(Y_train[:test_data_size])

    X_train = np.array(X_train[test_data_size:], dtype=np.int32)
    Y_train = np.array(Y_train[test_data_size:])


def string_to_vocab(string, max_document_length):
    x = np.zeros(max_document_length)

    i = 0
    for word in string.split(' '):
        x[i] = int(vocab_to_int[word])
        i += 1
        if i >= max_document_length:
            break

    return x

# def preprocess_data():
#     vocab_processor = VocabularyProcessor(max_document_length=max_sentence_length, vocabulary=vocab_to_int)
#     for row in range(len(X_train)):
#         print(row)
#         print(X_train[row])
#
#         for i in X_train[row][0].split(' '):
#             print(vocab_to_int[i], end='+ ')
#
#         X_train[row] = list(vocab_processor.transform(X_train[row]))
#         print(X_train[row])
#     raise Exception

def build_inputs(batch_size, num_steps):
    inputs = tf.placeholder(tf.int32, [None, num_steps], name='inputs')
    targets = tf.placeholder(tf.int32, [None, 2], name='targets')
    keep_prob = tf.placeholder(tf.float32, name='keep_prob')
    return inputs, targets, keep_prob

def build_output(lstm_output, in_size, out_size):
    print('---------------------')
    print('in_size', in_size)
    print('out_size', out_size)
    print('lstm_output', lstm_output.shape)
    seq_output = tf.concat(lstm_output, axis=1)
    print('seq_output', seq_output.shape)
    x = tf.reshape(seq_output, [-1, in_size])
    print('x', x.shape)

    with tf.variable_scope('softmax'):
        softmax_w = tf.Variable(tf.truncated_normal((in_size, out_size), stddev=0.1))
        softmax_b = tf.Variable(tf.zeros(out_size))

    logits = tf.matmul(x, softmax_w) + softmax_b
    print('logits size', logits.shape)
    out = tf.nn.softmax(logits, name='predictions')
    return out, logits


def build_loss(logits, targets, lstm_size, num_classes):
    # y_one_hot = tf.one_hot(targets, num_classes)
    #
    print('targets', targets, targets.shape)
    print('logits', logits, logits.get_shape())
    # print('num_classes', num_classes)
    # print('y_one_hot', y_one_hot)
    # y_reshaped = tf.reshape(y_one_hot, logits.get_shape())
    loss = tf.nn.softmax_cross_entropy_with_logits(logits=logits, labels=targets)
    loss = tf.reduce_mean(loss)
    return loss



def build_lstm(lstm_size, num_layers, batch_size, keep_prob):
    def build_cell(num_units, keep_prob):
        lstm = tf.contrib.rnn.BasicLSTMCell(num_units)
        drop = tf.contrib.rnn.DropoutWrapper(lstm, output_keep_prob=keep_prob)

        return drop

    ### Build the LSTM Cell
    # Use a basic LSTM cell
    print('lstm_size', lstm_size)
    print('batch_size', batch_size)
    lstm = tf.contrib.rnn.BasicLSTMCell(lstm_size)

    # Add dropout to the cell outputs
    drop = tf.contrib.rnn.DropoutWrapper(lstm, output_keep_prob=keep_prob)

    # Stack up multiple LSTM layers, for deep learning
    cell = tf.contrib.rnn.MultiRNNCell([build_cell(lstm_size, keep_prob) for _ in range(num_layers)])
    #cell = tf.contrib.rnn.MultiRNNCell([drop] * num_layers)
    initial_state = cell.zero_state(batch_size, tf.float32)

    return cell, initial_state



def build_optimizer(loss, learning_rate, grad_clip):
    # Optimizer for training, using gradient clipping to control exploding gradients
    tvars = tf.trainable_variables()
    grads, _ = tf.clip_by_global_norm(tf.gradients(loss, tvars), grad_clip)
    train_op = tf.train.AdamOptimizer(learning_rate)
    optimizer = train_op.apply_gradients(zip(grads, tvars))

    return optimizer

def batch_features_labels(features, labels, batch_size):
    """
    Split features and labels into batches
    """
    for start in range(0, len(features), batch_size):
        end = min(start + batch_size, len(features))
        yield features[start:end], labels[start:end]


def get_batches(X_train, batch_size, num_steps):
    pass

def create_neural_network():
    global vocab_to_int, int_to_vocab, counter
    vocab_to_int, int_to_vocab = create_lookup_tables(counter)
    preprocess_data()
    print('X_train', X_train.shape)
    print('Y_train', Y_train.shape)
    print('X_test', X_test.shape)
    print('Y_test', Y_test.shape)
    print('size of vocabulary', len(vocab_to_int))

    epochs = 20
    #sequence_length = max_sentence_length
    #embedding_length = len(vocab_to_int)
    num_classes = 2
    grad_clip = 5

    batch_size = 10                 # Sequences per batch
    num_steps = 500 # Number of sequence steps per batch
    lstm_size = 128                 # Size of hidden layers in LSTMs
    num_layers = 2                  # Number of LSTM layers
    learning_rate = 0.01            # Learning rate
    keep_prob = 0.5                 # Dropout keep probability

    tf.reset_default_graph()

    # Build the input placeholder tensors
    inputs, targets, keep_prob = build_inputs(batch_size, num_steps)

    # Build the LSTM cell
    cell, initial_state = build_lstm(lstm_size, num_layers, batch_size, keep_prob)

    ### Run the data through the RNN layers
    # First, one-hot encode the input tokens
    x_one_hot = tf.one_hot(inputs, num_classes)
    print('inputs', inputs.shape)
    print('num_classes', num_classes)
    print('x_one_hot', x_one_hot.shape)

    # Run each sequence step through the RNN with tf.nn.dynamic_rnn
    outputs, state = tf.nn.dynamic_rnn(cell, x_one_hot, initial_state=initial_state)
    print('outputs', outputs.shape)
    final_state = state

    # Get softmax predictions and logits
    prediction, logits = build_output(outputs, lstm_size, num_classes)

    # Loss and optimizer (with gradient clipping)
    loss = build_loss(logits, targets, lstm_size, num_classes)
    optimizer = build_optimizer(loss, learning_rate, grad_clip)

    with tf.Session() as sess:
        sess.run(tf.global_variables_initializer())

        counter = 0
        for e in range(epochs):
            # Train network
            new_state = sess.run(initial_state)
            total_loss = 0
            for x, y in batch_features_labels(X_train, Y_train, batch_size):
                print('x', x.shape)
                print('y', y.shape)
                counter += 1
                start = time.time()
                feed = {inputs: x,
                        targets: y,
                        keep_prob: 0.5,
                        initial_state: new_state}

                batch_loss, new_state, _ = sess.run([loss,
                                                     final_state,
                                                     optimizer],
                                                    feed_dict=feed)

                end = time.time()
                print('Epoch: {}/{}... '.format(e+1, epochs),
                      'Training Step: {}... '.format(counter),
                      'Training loss: {:.4f}... '.format(batch_loss),
                      '{:.4f} sec/batch'.format((end-start)))


if __name__ == '__main__':
    preprocess()