# -*- coding: utf-8 -*-
import codecs
import numpy as np
import cPickle
from keras import Input
from keras.callbacks import ModelCheckpoint, EarlyStopping
from keras.engine import Model
from keras.layers.merge import concatenate
from keras.layers import Embedding, Dense, Dropout, LSTM
from preprocessing import BATCH_SIZE, EMB_DIM, CONTEXT_LENGTH, UNKNOWN, PADDING, \
    TARGET_LENGTH, generate_arrays_from_file_lstm
from subprocess import check_output

print(u"Dimension:", EMB_DIM)
print(u"Input length:", CONTEXT_LENGTH)
#  --------------------------------------------------------------------------------------------------------------------
word_to_index = cPickle.load(open(u"data/w2i.pkl"))
print(u"Vocabulary Size:", len(word_to_index))

vectors = {UNKNOWN: np.ones(EMB_DIM), PADDING: np.ones(EMB_DIM)}
for line in codecs.open(u"../data/glove.twitter." + str(EMB_DIM) + u"d.txt", encoding=u"utf-8"):
    if line.strip() == "":
        continue
    t = line.split()
    vectors[t[0]] = [float(x) for x in t[1:]]
print(u'Twitter vectors...', len(vectors))

weights = np.zeros((len(word_to_index), EMB_DIM))
oov = 0
for w in word_to_index:
    if w in vectors:
        weights[word_to_index[w]] = vectors[w]
    else:
        weights[word_to_index[w]] = np.random.normal(size=(EMB_DIM,), scale=0.3)
        oov += 1

weights = np.array([weights])
print(u'Done preparing vectors...')
print(u"OOV (no vectors):", oov)
#  --------------------------------------------------------------------------------------------------------------------
print(u'Building model...')
embeddings = Embedding(len(word_to_index), EMB_DIM, input_length=CONTEXT_LENGTH, weights=weights)
# shared embeddings between all language input layers

context_words_forward = Input(shape=(CONTEXT_LENGTH,))
cwf = embeddings(context_words_forward)
cwf = LSTM(300)(cwf)
cwf = Dense(300)(cwf)
cwf = Dropout(0.5)(cwf)

context_words_backward = Input(shape=(CONTEXT_LENGTH,))
cwb = embeddings(context_words_backward)
cwb = LSTM(300, go_backwards=True)(cwb)
cwb = Dense(300)(cwb)
cwb = Dropout(0.5)(cwb)

entities_strings_forward = Input(shape=(CONTEXT_LENGTH,))
esf = embeddings(entities_strings_forward)
esf = LSTM(300)(esf)
esf = Dense(300)(esf)
esf = Dropout(0.5)(esf)

entities_strings_backward = Input(shape=(CONTEXT_LENGTH,))
esb = embeddings(entities_strings_backward)
esb = LSTM(300)(esb)
esb = Dense(300)(esb)
esb = Dropout(0.5)(esb)

target_string = Input(shape=(TARGET_LENGTH,))
ts = Embedding(len(word_to_index), EMB_DIM, input_length=TARGET_LENGTH, weights=weights)(target_string)
ts = LSTM(50)(ts)
ts = Dense(50)(ts)
ts = Dropout(0.5)(ts)

output_polygon_size = 2
inp = concatenate([cwf, cwb, esf, esb, ts])
inp = Dense(units=(180 / output_polygon_size) * (360 / output_polygon_size), activation=u'softmax')(inp)
model = Model(inputs=[context_words_forward, context_words_backward, entities_strings_forward,
                      entities_strings_backward, target_string], outputs=[inp])
model.compile(loss=u'categorical_crossentropy', optimizer=u'rmsprop', metrics=[u'accuracy'])

print(u'Finished building model...')
#  --------------------------------------------------------------------------------------------------------------------
# checkpoint = ModelCheckpoint(filepath="../data/weights", verbose=0)
checkpoint = ModelCheckpoint(filepath=u"../data/weights.{epoch:02d}-{acc:.2f}.hdf5", verbose=0)
early_stop = EarlyStopping(monitor=u'acc', patience=5)
file_name = u"../data/train_wiki_uniform.txt"
model.fit_generator(generate_arrays_from_file_lstm(file_name, word_to_index),
                    steps_per_epoch=int(check_output(["wc", file_name]).split()[0]) / BATCH_SIZE,
                    epochs=200, callbacks=[checkpoint, early_stop])