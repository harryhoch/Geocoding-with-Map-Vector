# -*- coding: utf-8 -*-
import codecs
import numpy as np
import cPickle
from keras import Input
from keras.callbacks import ModelCheckpoint, EarlyStopping
from keras.engine import Model
from keras.layers.merge import concatenate
from keras.layers import Embedding, Dense, LSTM, Dropout, Conv1D, GlobalMaxPooling1D
from preprocessing import generate_arrays_from_file, GRID_SIZE, BATCH_SIZE, EMB_DIM, CONTEXT_LENGTH, UNKNOWN, PADDING, \
    TARGET_LENGTH
from subprocess import check_output

print(u"Dimension:", EMB_DIM)
print(u"Input length:", CONTEXT_LENGTH)

words = cPickle.load(open(u"data/vocab_words.pkl"))
locations = cPickle.load(open(u"data/vocab_locations.pkl"))
vocabulary = words.union(locations)
print(u"Vocabulary Size:", len(vocabulary))
#  --------------------------------------------------------------------------------------------------------------------
print(u'Preparing vectors...')
word_to_index = dict([(w, i) for i, w in enumerate(vocabulary)])

vectors = {UNKNOWN: np.ones(EMB_DIM), PADDING: np.ones(EMB_DIM)}
# for line in codecs.open(u"../data/glove.twitter." + str(EMB_DIM) + u"d.txt", encoding=u"utf-8"):
#     if line.strip() == "":
#         continue
#     t = line.split()
#     vectors[t[0]] = [float(x) for x in t[1:]]
# print(u'Loaded Twitter vectors...', len(vectors))

# for line in codecs.open(u"../data/glove." + str(EMB_DIM) + u"d.txt", encoding=u"utf-8"):
#     if line.strip() == u"":
#         continue
#     t = line.split()
#     vectors[t[0]] = [float(x) for x in t[1:]]
# print(u'Loaded GloVe vectors...', len(vectors))

weights = np.zeros((len(vocabulary), EMB_DIM))
oov = 0
for w in vocabulary:
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
embeddings = Embedding(len(vocabulary), EMB_DIM, input_length=CONTEXT_LENGTH, weights=weights)
near_words = Input(shape=(CONTEXT_LENGTH,))
nw = embeddings(near_words)
nw = Conv1D(500, 2, activation='relu', strides=1)(nw)
nw = GlobalMaxPooling1D()(nw)
nw = Dense(200)(nw)
nw = Dropout(0.3)(nw)

far_words = Input(shape=(CONTEXT_LENGTH,))
fw = embeddings(far_words)
fw = Conv1D(500, 2, activation='relu', strides=1)(fw)
fw = GlobalMaxPooling1D()(fw)
fw = Dense(200)(fw)
fw = Dropout(0.3)(fw)

near_entities_strings = Input(shape=(CONTEXT_LENGTH,))
nes = embeddings(near_entities_strings)
nes = Conv1D(500, 2, activation='relu', strides=1)(nes)
nes = GlobalMaxPooling1D()(nes)
nes = Dense(200)(nes)
nes = Dropout(0.3)(nes)

far_entities_strings = Input(shape=(CONTEXT_LENGTH,))
fes = embeddings(far_entities_strings)
fes = Conv1D(500, 2, activation='relu', strides=1)(fes)
fes = GlobalMaxPooling1D()(fes)
fes = Dense(200)(fes)
fes = Dropout(0.3)(fes)

near_entities_coord = Input(shape=((180 / GRID_SIZE) * (360 / GRID_SIZE),))
nec = Dense(200, activation='relu', input_dim=(180 / GRID_SIZE) * (360 / GRID_SIZE))(near_entities_coord)
nec = Dropout(0.3)(nec)

far_entities_coord = Input(shape=((180 / GRID_SIZE) * (360 / GRID_SIZE),))
fec = Dense(200, activation='relu', input_dim=(180 / GRID_SIZE) * (360 / GRID_SIZE))(far_entities_coord)
fec = Dropout(0.3)(fec)

target_coord = Input(shape=((180 / GRID_SIZE) * (360 / GRID_SIZE),))
tc = Dense(500, activation='relu', input_dim=(180 / GRID_SIZE) * (360 / GRID_SIZE))(target_coord)
tc = Dropout(0.3)(tc)

target_string = Input(shape=(TARGET_LENGTH,))
ts = Embedding(len(vocabulary), EMB_DIM, input_length=TARGET_LENGTH, weights=weights)(target_string)
ts = Conv1D(500, 2, activation='relu', strides=1)(ts)
ts = GlobalMaxPooling1D()(ts)
ts = Dropout(0.3)(ts)

inp = concatenate([nw, fw, nes, fes, nec, fec, tc, ts])
inp = Dense(units=(180 / GRID_SIZE) * (360 / GRID_SIZE), activation='softmax')(inp)
model = Model(inputs=[near_words, far_words, near_entities_strings, far_entities_strings,
                      near_entities_coord, far_entities_coord, target_coord, target_string], outputs=[inp])
model.compile(loss='categorical_crossentropy', optimizer='rmsprop', metrics=['accuracy'])

print(u'Finished building model...')
#  --------------------------------------------------------------------------------------------------------------------
checkpoint = ModelCheckpoint(filepath="../data/weights", verbose=0)
# checkpoint = ModelCheckpoint(filepath="../data/weights.{epoch:02d}-{acc:.2f}.hdf5", verbose=0)
early_stop = EarlyStopping(monitor='acc', patience=5)
file_name = u"../data/train_wiki_uniform.txt"
model.fit_generator(generate_arrays_from_file(file_name, word_to_index),
                    steps_per_epoch=int(check_output(["wc", file_name]).split()[0]) / BATCH_SIZE,
                    epochs=100, callbacks=[checkpoint, early_stop])
