# -*- coding: utf-8 -*-
import codecs
import numpy as np
import cPickle
from keras.callbacks import ModelCheckpoint
from keras.engine import Merge
from keras.layers import Embedding, Dense, Dropout, Conv1D, GlobalMaxPooling1D
from keras.models import Sequential
from preprocessing import generate_arrays_from_file, GRID_SIZE
from subprocess import check_output

UNKNOWN, PADDING = u"<unknown>", u"0.0"
dimension, input_length = 100, 100
print(u"Dimension:", dimension)
print(u"Input length:", input_length)

vocabulary = cPickle.load(open("data/vocabulary.pkl"))
print(u"Vocabulary Size:", len(vocabulary))
#  --------------------------------------------------------------------------------------------------------------------
print(u'Preparing vectors...')
word_to_index = dict([(w, i) for i, w in enumerate(vocabulary)])

vectors = {UNKNOWN: np.ones(dimension), PADDING: np.ones(dimension)}
for line in codecs.open("../data/glove.twitter." + str(dimension) + "d.txt", encoding="utf-8"):
    if line.strip() == "":
        continue
    t = line.split()
    vectors[t[0]] = [float(x) for x in t[1:]]
print(u'Loaded Twitter vectors...', len(vectors))

for line in codecs.open("../data/glove." + str(dimension) + "d.txt", encoding="utf-8"):
    if line.strip() == "":
        continue
    t = line.split()
    vectors[t[0]] = [float(x) for x in t[1:]]
print(u'Loaded GloVe vectors...', len(vectors))

weights = np.zeros((len(vocabulary), dimension))
for w in vocabulary:
    if w in vectors:
        weights[word_to_index[w]] = vectors[w]
weights = np.array([weights])
print(u'Done preparing vectors...')
#  --------------------------------------------------------------------------------------------------------------------
print(u'Building model...')
model_left = Sequential()
model_left.add(Embedding(len(vocabulary), dimension, input_length=input_length, weights=weights))
model_left.add(Conv1D(500, 2, activation='relu', subsample_length=1))
model_left.add(GlobalMaxPooling1D())
model_left.add(Dense(100))
model_left.add(Dropout(0.2))

model_right = Sequential()
model_right.add(Embedding(len(vocabulary), dimension, input_length=input_length, weights=weights))
model_right.add(Conv1D(500, 2, activation='relu', subsample_length=1))
model_right.add(GlobalMaxPooling1D())
model_right.add(Dense(100))
model_right.add(Dropout(0.2))

model_entities = Sequential()
model_entities.add(Dense(100, activation='relu', input_dim=(180 / GRID_SIZE) * (360 / GRID_SIZE)))
model_entities.add(Dropout(0.2))

model_target = Sequential()
model_target.add(Dense(500, activation='relu', input_dim=(180 / GRID_SIZE) * (360 / GRID_SIZE)))
model_target.add(Dropout(0.2))

merged_model = Sequential()
merged_model.add(Merge([model_left, model_right, model_entities, model_target], mode='concat', concat_axis=1))
merged_model.add(Dense(2, activation='linear'))
merged_model.compile(loss='mse', optimizer='adam')

print(u'Finished building model...')
#  --------------------------------------------------------------------------------------------------------------------
checkpoint = ModelCheckpoint(filepath="../data/weights", verbose=0)
# checkpoint = ModelCheckpoint(filepath="../data/weights.{epoch:02d}-{loss:.1f}.hdf5", verbose=0)
file_name = u"data/eval_lgl.txt"
merged_model.fit_generator(generate_arrays_from_file(file_name, word_to_index, input_length, regression=True),
                           samples_per_epoch=int(check_output(["wc", file_name]).split()[0]),
                           nb_epoch=100, callbacks=[checkpoint])
