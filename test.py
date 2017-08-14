# -*- coding: utf-8 -*-
import codecs

import numpy as np
import cPickle
import sqlite3
# import pprint
import sys
from geopy.distance import great_circle
from keras.models import load_model
from subprocess import check_output
from preprocessing import get_coordinates, print_stats, index_to_coord, generate_strings_from_file
from preprocessing import generate_arrays_from_file
# import matplotlib.pyplot as plt

if len(sys.argv) > 1:
    data = sys.argv[1]
else:
    data = u"lgl"

input_length = 200
print(u"Input length:", input_length)
print(u"Testing:", data)
vocabulary = cPickle.load(open(u"./data/vocabulary.pkl"))
print(u"Vocabulary Size:", len(vocabulary))
#  --------------------------------------------------------------------------------------------------------------------
word_to_index = dict([(w, i) for i, w in enumerate(vocabulary)])
#  --------------------------------------------------------------------------------------------------------------------
print(u'Loading model...')
model = load_model(u"../data/weights_all_cnn")
print(u'Finished loading model...')
#  --------------------------------------------------------------------------------------------------------------------
print(u'Crunching numbers, sit tight...')
save_errors = codecs.open(u"errors.tsv", u"w", encoding="utf-8")
conn = sqlite3.connect(u'../data/geonames.db')
file_name = u"data/eval_" + data + u".txt"
choice = []
for p, (y, name, context) in zip(model.predict_generator(generate_arrays_from_file(file_name, word_to_index, input_length, train=False, oneDim=False),
        steps=int(check_output(["wc", file_name]).split()[0]) / 64), generate_strings_from_file(file_name)):

    confidence = max(p)
    p = index_to_coord(np.argmax(p))
    candidates = get_coordinates(conn.cursor(), name, pop_only=True)

    if len(candidates) == 0:
        print(u"Don't have an entry for", name, u"in GeoNames")
        continue

    # population = [sorted(get_coordinates(conn.cursor(), name, True), key=lambda (a, b, c, d): c, reverse=True)[0]]
    # THE ABOVE IS THE POPULATION ONLY BASELINE IMPLEMENTATION

    temp, distance = [], []
    for candidate in candidates:
        # distance.append((great_circle(y, (float(candidate[0]), float(candidate[1]))).kilometers, (float(candidate[0]), float(candidate[1]))))
        temp.append((great_circle(p, (float(candidate[0]), float(candidate[1]))).kilometers, (float(candidate[0]), float(candidate[1]))))
    best = sorted(temp, key=lambda (a, b): a)[0]
    choice.append(great_circle(best[1], y).kilometers)

    if best[0] > 161:
        # print(u"Gold:", y, u"Predicted:", p)
        save_errors.write(name + u"\t" + unicode(y[0]) + "\t" + unicode(y[1]) + u"\t" + unicode(p[0]) + u"\t" + unicode(p[1]) \
              + u"\t" + unicode(confidence) + u"\t" + unicode(best[0]) + u"\t" + context + u"\n")
        # print(u"Population:", population, u"Confidence", confidence)
        # print(u"Best GeoNames Candidate:", sorted(distance, key=lambda (a, b): a)[0], u"My Distance:", choice[-1])
    # print("-----------------------------------------------------------------------------------------------------------")

# print_stats(choice)
# print(u"Processed file", file_name)

# ---------------- DIAGNOSTICS --------------------
# pprint.pprint(model.get_config())
# plt.plot(range(len(choice)), np.log(1 + np.asarray(sorted(choice))))
# plt.xlabel(u"Predictions")
# plt.ylabel(u'Error Size')
# plt.title(u"Some Chart")
# plt.savefig(u'test.png', transparent=True)
# plt.show()

# W = model.layers[-1].get_weights()
# W = np.concatenate((W[0], np.array([W[1]])), axis=0)
# W = np.rot90(W)
# cPickle.dump(W, open("./data/W.pkl", "w"))
# ------------- END OF DIAGNOSTICS -----------------