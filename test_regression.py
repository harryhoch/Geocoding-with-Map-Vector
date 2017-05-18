# -*- coding: utf-8 -*-
import cPickle
import sqlite3
# import pprint
from geopy.distance import great_circle
from keras.models import load_model
from subprocess import check_output
from preprocessing import get_coordinates, print_stats, generate_strings_from_file
from preprocessing import generate_arrays_from_file
# import matplotlib.pyplot as plt

input_length = 100
print(u"Input length:", input_length)

vocabulary = cPickle.load(open(u"./data/vocabulary.pkl"))
print(u"Vocabulary Size:", len(vocabulary))
#  --------------------------------------------------------------------------------------------------------------------
word_to_index = dict([(w, i) for i, w in enumerate(vocabulary)])
#  --------------------------------------------------------------------------------------------------------------------
print(u'Loading model...')
model = load_model(u"../data/weights")
print(u'Finished loading model...')
#  --------------------------------------------------------------------------------------------------------------------
print(u'Crunching numbers, sit tight...')
conn = sqlite3.connect(u'../data/geonames.db')
file_name = u"data/eval_wiki.txt"
choice = []
for p, (y, name, context) in zip(model.predict_generator(generate_arrays_from_file(file_name, word_to_index, input_length, train=False, regression=True),
                   val_samples=int(check_output(["wc", file_name]).split()[0])), generate_strings_from_file(file_name)):
    candidates = get_coordinates(conn.cursor(), name, pop_only=True)
    # candidates = [sorted(get_coordinates(conn.cursor(), name, True), key=lambda (a, b, c): c, reverse=True)[0]]  # population only
    if len(candidates) == 0:
        print(u"Don't have an entry for", name, u"in GeoNames")
        continue
    temp, distance = [], []
    for can in candidates:
        # distance.append(great_circle(y, (float(candidate[0]), float(candidate[1]))).kilometers)
        temp.append((great_circle((p[0], p[1]), (float(can[0]), float(can[1]))).kilometers, (float(can[0]), float(can[1]))))
    best = sorted(temp, key=lambda (a, b): a)[0]
    choice.append(great_circle(best[1], y).kilometers)
    # print(context)
    # print(name, u"Predicted:", p, u"Gold:", y, u"Distance:", choice[-1])
    # print(candidates)
    # if sorted(distance)[0] > 101:
    #     raise Exception(u"OMW! What's happening?!", name)
    # print("-----------------------------------------------------------------------------------------------------------")

print_stats(choice)
print(u"Processed file", file_name)
# pprint.pprint(model.get_config())
# plt.plot(range(len(choice)), sorted(choice))
# plt.xlabel(u"Examples")
# plt.ylabel(u'Error')
# plt.show()
