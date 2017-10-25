# -*- coding: utf-8 -*-
import codecs
import cPickle
from collections import Counter
import matplotlib.pyplot as plt
import spacy
import numpy as np
import sqlite3
from geopy.distance import great_circle
from matplotlib import pyplot, colors
from scipy.spatial.distance import euclidean


# -------- GLOBAL CONSTANTS -------- #
BATCH_SIZE = 64
CONTEXT_LENGTH = 200
UNKNOWN = u"<unknown>"
PADDING = u"0"
EMB_DIM = 50
TARGET_LENGTH = 15
# -------- GLOBAL CONSTANTS -------- #


def print_stats(accuracy):
    """"""
    print("==============================================================================================")
    accuracy = np.log(np.array(accuracy) + 1)
    print(u"Median error:", np.median(sorted(accuracy)))
    print(u"Mean error:", np.mean(accuracy))
    k = np.log(161)  # This is the k in accuracy@k metric (see my Survey Paper for details)
    print u"Accuracy to 161 km: ", sum([1.0 for dist in accuracy if dist < k]) / len(accuracy)
    print u"AUC = ", np.trapz(accuracy) / (np.log(20039) * (len(accuracy) - 1))  # Trapezoidal rule.
    print("==============================================================================================")


def pad_list(size, a_list, from_left):
    """"""
    while len(a_list) < size:
        if from_left:
            a_list = [PADDING] + a_list
        else:
            a_list += [PADDING]
    return a_list


def coord_to_index(coordinates, polygon_size):
    """"""
    latitude = float(coordinates[0]) - 90 if float(coordinates[0]) != -90 else -179.99  # The two edge cases must
    longitude = float(coordinates[1]) + 180 if float(coordinates[1]) != 180 else 359.99  # get handled differently!
    if longitude < 0:
        longitude = -longitude
    if latitude < 0:
        latitude = -latitude
    x = int(360 / polygon_size) * int(latitude / polygon_size)
    y = int(longitude / polygon_size)
    return x + y if 0 <= x + y <= int(360 / polygon_size) * int(180 / polygon_size) else Exception(u"Shock horror!!")


def index_to_coord(index, polygon_size):
    """"""
    x = int(index / (360 / polygon_size))
    y = index % int(360 / polygon_size)
    if x > int(90 / polygon_size):
        x = -int((x - (90 / polygon_size)) * polygon_size)
    else:
        x = int(((90 / polygon_size) - x) * polygon_size)
    if y < int(180 / polygon_size):
        y = -int(((180 / polygon_size) - y) * polygon_size)
    else:
        y = int((y - (180 / polygon_size)) * polygon_size)
    return x, y


def get_coordinates(con, loc_name):
    """"""
    result = con.execute(u"SELECT METADATA FROM GEO WHERE NAME = ?", (loc_name.lower(),)).fetchone()
    if result:
        result = eval(result[0])  # Do not remove the sorting, the function below assumes sorted results!
        return sorted(result, key=lambda (a, b, c, d): c, reverse=True)
    else:
        return []


def construct_spatial_grid(a_list, polygon_size):
    """"""
    g = np.zeros(int(360 / polygon_size) * int(180 / polygon_size))
    if len(a_list) == 0:
        return g
    max_pop = a_list[0][2] if a_list[0][2] > 0 else 1
    for s in a_list:
        index = coord_to_index((s[0], s[1]), polygon_size)
        g[index] += float(max(s[2], 1)) / max_pop
    return g / max(g) if max(g) > 0.0 else g


def construct_loc2vec(target, near, far, polygon_size):
    """"""
    target = construct_spatial_grid(target, polygon_size)
    near = construct_spatial_grid(near, polygon_size)
    far = construct_spatial_grid(far, polygon_size)
    l2v = near + far + target
    return l2v / max(l2v)


def merge_lists(grids):
    """"""
    out = []
    for g in grids:
        out.extend(g)
    return out


def populate_sql():
    """Create and populate the sqlite database with GeoNames data"""
    geo_names = {}
    p_map = {"PPLC": 100000, "PCLI": 100000, "PCL": 100000, "PCLS": 10000, "PCLF": 10000, "CONT": 100000, "RGN": 100000}

    for line in codecs.open(u"../data/allCountries.txt", u"r", encoding=u"utf-8"):
        line = line.split("\t")
        feat_code = line[7]
        class_code = line[6]
        pop = int(line[14])
        for name in [line[1], line[2]] + line[3].split(","):
            name = name.lower()
            if len(name) != 0:
                if name in geo_names:
                    already_have_entry = False
                    for item in geo_names[name]:
                        if great_circle((float(line[4]), float(line[5])), (item[0], item[1])).km < 100:
                            if item[2] >= pop:
                                already_have_entry = True
                    if not already_have_entry:
                        pop = get_population(class_code, feat_code, p_map, pop)
                        geo_names[name].add((float(line[4]), float(line[5]), pop, feat_code))
                else:
                    pop = get_population(class_code, feat_code, p_map, pop)
                    geo_names[name] = {(float(line[4]), float(line[5]), pop, feat_code)}

    conn = sqlite3.connect(u'../data/geonames.db')
    c = conn.cursor()
    # c.execute("CREATE TABLE GEO (NAME VARCHAR(100) PRIMARY KEY NOT NULL, METADATA VARCHAR(5000) NOT NULL);")
    c.execute(u"DELETE FROM GEO")  # alternatively, delete the database file.
    conn.commit()

    for gn in geo_names:
        c.execute(u"INSERT INTO GEO VALUES (?, ?)", (gn, str(list(geo_names[gn]))))
    print(u"Entries saved:", len(geo_names))
    conn.commit()
    conn.close()


def get_population(class_code, feat_code, p_map, pop):
    """"""
    if pop == 0 and class_code in ["A", "P", "L"]:
        pop = p_map.get(feat_code, 0)
    return pop


def generate_training_data():
    """Prepare Wikipedia training data."""
    conn = sqlite3.connect(u'../data/geonames.db')
    c = conn.cursor()
    nlp = spacy.load(u'en')
    input = codecs.open(u"../data/geowiki.txt", u"r", encoding=u"utf-8")
    o = codecs.open(u"../data/train_wiki.txt", u"w", encoding=u"utf-8")
    lat, lon = u"", u""
    target, string = u"", u""
    skipped = 0

    for line in input:
        if len(line.strip()) == 0:
            continue
        limit = 0
        if line.startswith(u"NEW ARTICLE::"):
            if len(string.strip()) > 0 and len(target) != 0:
                locations_near, locations_far = [], []
                doc = nlp(string)
                for d in doc:
                    if d.text == target[0]:
                        if u" ".join(target) == u" ".join([t.text for t in doc[d.i:d.i + len(target)]]):
                            near_inp = [x for x in doc[max(0, d.i - CONTEXT_LENGTH / 2):d.i]] + \
                                       [x for x in doc[d.i + len(target): d.i + len(target) + CONTEXT_LENGTH / 2]]
                            far_inp = [x for x in doc[max(0, d.i - CONTEXT_LENGTH):max(0, d.i - CONTEXT_LENGTH / 2)]] + \
                                      [x for x in doc[d.i + len(target) + CONTEXT_LENGTH / 2: d.i + len(target) + CONTEXT_LENGTH]]
                            near_out, far_out = [], []
                            location = u""
                            for (out_list, in_list, is_near) in [(near_out, near_inp, True), (far_out, far_inp, False)]:
                                for index, item in enumerate(in_list):
                                    if item.ent_type_ in [u"GPE", u"FACILITY", u"LOC", u"FAC"]:
                                        if item.ent_iob_ == u"B" and item.text.lower() == u"the":
                                            out_list.append(item.text.lower())
                                        else:
                                            location += item.text + u" "
                                            out_list.append(u"**LOC**" + item.text.lower())
                                    elif item.ent_type_ in [u"PERSON", u"DATE", u"TIME", u"PERCENT", u"MONEY",
                                                            u"QUANTITY", u"CARDINAL", u"ORDINAL"]:
                                        out_list.append(PADDING)
                                    elif item.is_punct:
                                        out_list.append(PADDING)
                                    elif item.is_digit or item.like_num:
                                        out_list.append(PADDING)
                                    elif item.like_email:
                                        out_list.append(PADDING)
                                    elif item.like_url:
                                        out_list.append(PADDING)
                                    elif item.is_stop:
                                        out_list.append(PADDING)
                                    else:
                                        out_list.append(item.lemma_)
                                    if location.strip() != u"" and (item.ent_type == 0 or index == len(in_list) - 1):
                                        location = location.strip()
                                        coords = get_coordinates(c, location)
                                        if len(coords) > 0 and location != u" ".join(target):
                                            if is_near:
                                                locations_near.append(coords)
                                            else:
                                                locations_far.append(coords)
                                        else:
                                            offset = 1 if index == len(in_list) - 1 else 0
                                            for i in range(index - len(location.split()), index):
                                                out_list[i + offset] = in_list[i + offset].lemma_ \
                                                if in_list[i + offset].is_alpha and location != u" ".join(target) else PADDING
                                        location = u""
                            target_grid = get_coordinates(c, u" ".join(target))
                            if len(target_grid) == 0:
                                skipped += 1
                                break
                            entities_near = merge_lists(locations_near)
                            entities_far = merge_lists(locations_far)
                            locations_near, locations_far = [], []
                            o.write(lat + u"\t" + lon + u"\t" + str(near_out) + u"\t" + str(far_out) + u"\t")
                            o.write(str(target_grid) + u"\t" + str([t.lower() for t in target][:TARGET_LENGTH]))
                            o.write(u"\t" + str(entities_near) + u"\t" + str(entities_far) + u"\n")
                            limit += 1
                            if limit > 29:
                                break
            line = line.strip().split("\t")
            if u"(" in line[1]:
                line[1] = line[1].split(u"(")[0].strip()
            if line[1].strip().startswith(u"Geography of "):
                target = line[1].replace(u"Geography of ", u"").split()
            elif u"," in line[1]:
                target = line[1].split(u",")[0].strip().split()
            else:
                target = line[1].split()
            lat = line[2]
            lon = line[3]
            string = ""
            print(u"Processed", limit, u"Skipped:", skipped, u"Name:", u" ".join(target))
        else:
            string += line
    o.close()


def generate_evaluation_data(corpus, file_name):
    """"""
    conn = sqlite3.connect(u'../data/geonames.db')
    c = conn.cursor()
    nlp = spacy.load(u'en')
    directory = u"../data/" + corpus + u"/"
    o = codecs.open(u"data/eval_" + corpus + file_name + u".txt", u"w", encoding=u"utf-8")
    line_no = 0 if corpus == u"lgl" else -1

    for line in codecs.open(u"data/" + corpus + file_name + u".txt", u"r", encoding=u"utf-8"):
        line_no += 1
        if len(line.strip()) == 0:
            continue
        for toponym in line.split(u"||")[:-1]:
            captured = False
            doc = nlp(codecs.open(directory + str(line_no), u"r", encoding=u"utf-8").read())
            locations_near, locations_far = [], []
            toponym = toponym.split(u",,")
            target = [t.text for t in nlp(toponym[1])]
            ent_length = len(u" ".join(target))
            lat, lon = toponym[2], toponym[3]
            start, end = int(toponym[4]), int(toponym[5])
            for d in doc:
                if d.text == target[0]:
                    if u" ".join(target) == u" ".join([t.text for t in doc[d.i:d.i + len(target)]]):
                        if abs(d.idx - start) > 4 or abs(d.idx + ent_length - end) > 4:
                            continue
                        captured = True
                        near_inp = [x for x in doc[max(0, d.i - CONTEXT_LENGTH / 2):d.i]] + \
                                   [x for x in doc[d.i + len(target): d.i + len(target) + CONTEXT_LENGTH / 2]]
                        far_inp = [x for x in doc[max(0, d.i - CONTEXT_LENGTH):max(0, d.i - CONTEXT_LENGTH / 2)]] + \
                                  [x for x in doc[d.i + len(target) + CONTEXT_LENGTH / 2: d.i + len(target) + CONTEXT_LENGTH]]
                        near_out, far_out = [], []
                        location = u""
                        for (out_list, in_list, is_near) in [(near_out, near_inp, True), (far_out, far_inp, False)]:
                            for index, item in enumerate(in_list):
                                if item.ent_type_ in [u"GPE", u"FACILITY", u"LOC", u"FAC"]:
                                    if item.ent_iob_ == u"B" and item.text.lower() == u"the":
                                        out_list.append(item.text.lower())
                                    else:
                                        location += item.text + u" "
                                        out_list.append(u"**LOC**" + item.text.lower())
                                elif item.ent_type_ in [u"PERSON", u"DATE", u"TIME", u"PERCENT", u"MONEY",
                                                        u"QUANTITY", u"CARDINAL", u"ORDINAL"]:
                                    out_list.append(PADDING)
                                elif item.is_punct:
                                    out_list.append(PADDING)
                                elif item.is_digit or item.like_num:
                                    out_list.append(PADDING)
                                elif item.like_email:
                                    out_list.append(PADDING)
                                elif item.like_url:
                                    out_list.append(PADDING)
                                elif item.is_stop:
                                    out_list.append(PADDING)
                                else:
                                    out_list.append(item.lemma_)
                                if location.strip() != u"" and (item.ent_type == 0 or index == len(in_list) - 1):
                                    location = location.strip()
                                    coords = get_coordinates(c, location)
                                    if len(coords) > 0 and location != u" ".join(target):
                                        if is_near:
                                            locations_near.append(coords)
                                        else:
                                            locations_far.append(coords)
                                    else:
                                        offset = 1 if index == len(in_list) - 1 else 0
                                        for i in range(index - len(location.split()), index):
                                            out_list[i + offset] = in_list[i + offset].lemma_ \
                                                if in_list[i + offset].is_alpha and location != u" ".join(target) else PADDING
                                    location = u""

                        lookup = toponym[0] if corpus != u"wiki" else toponym[1]
                        target_grid = get_coordinates(c, lookup)
                        if len(target_grid) == 0:
                            raise Exception(u"No entry in the database!", lookup)
                        entities_near = merge_lists(locations_near)
                        entities_far = merge_lists(locations_far)
                        locations_near, locations_far = [], []
                        o.write(lat + u"\t" + lon + u"\t" + str(near_out) + u"\t" + str(far_out) + u"\t")
                        o.write(str(target_grid) + u"\t" + str([t.lower() for t in lookup.split()][:TARGET_LENGTH]))
                        o.write(u"\t" + str(entities_near) + u"\t" + str(entities_far) + u"\n")
            if not captured:
                print line_no, line, target, start, end
    o.close()


def visualise_2D_grid(x, title, log=False):
    """"""
    if log:
        x = np.log10(x)
    cmap2 = colors.LinearSegmentedColormap.from_list('my_colormap', ['white', 'grey', 'black'])
    img2 = pyplot.imshow(x, cmap=cmap2, interpolation='nearest')
    pyplot.colorbar(img2, cmap=cmap2)
    # plt.imshow(np.log(x + 1), cmap='gray', interpolation='nearest', vmin=0, vmax=np.log(255))
    plt.title(title)
    plt.savefig(title + ".png", dpi=200)
    plt.show()


def generate_vocabulary():
    """Prepare the vocabulary(ies) for training."""
    vocab_words, vocab_locations = {UNKNOWN, PADDING}, {UNKNOWN, PADDING}
    words, locations = [], []
    for f in [u"../data/train_wiki.txt"]:
        training_file = codecs.open(f, u"r", encoding=u"utf-8")
        for line in training_file:
            line = line.strip().split("\t")
            words.extend([w for w in eval(line[2]) if u"**LOC**" not in w])  # NEAR WORDS
            words.extend([w for w in eval(line[3]) if u"**LOC**" not in w])  # FAR WORDS
            locations.extend([w for w in eval(line[2]) if u"**LOC**" in w])  # NEAR ENTITIES
            locations.extend([w for w in eval(line[3]) if u"**LOC**" in w])  # FAR ENTITIES

    words = Counter(words)
    for word in words:
        if words[word] > 9:
            vocab_words.add(word)
    print(u"Words saved:", len(vocab_words))

    locations = Counter(locations)
    for location in locations:
        if locations[location] > 1:
            vocab_locations.add(location.replace(u"**LOC**", u""))
    print(u"Locations saved:", len(vocab_locations))

    vocabulary = vocab_words.union(vocab_locations)
    word_to_index = dict([(w, i) for i, w in enumerate(vocabulary)])
    cPickle.dump(word_to_index, open(u"data/w2i.pkl", "w"))


def generate_arrays_from_file(path, w2i, train=True):
    """"""
    while True:
        training_file = codecs.open(path, "r", encoding="utf-8")
        counter = 0
        near_words, far_words, near_entities, far_entities, labels = [], [], [], [], []
        near_entities_coord, far_entities_coord, target_coord, target_string = [], [], [], []
        for line in training_file:
            counter += 1
            line = line.strip().split("\t")
            labels.append(construct_spatial_grid([(float(line[0]), float(line[1]), 0)], 2))

            near = [w if u"**LOC**" not in w else PADDING for w in eval(line[2])]
            far = [w if u"**LOC**" not in w else PADDING for w in eval(line[3])]
            near_words.append(pad_list(CONTEXT_LENGTH, near, from_left=True))
            far_words.append(pad_list(CONTEXT_LENGTH, far, from_left=False))

            near = [w.replace(u"**LOC**", u"") if u"**LOC**" in w else PADDING for w in eval(line[2])]
            far = [w.replace(u"**LOC**", u"") if u"**LOC**" in w else PADDING for w in eval(line[3])]
            near_entities.append(pad_list(CONTEXT_LENGTH, near, from_left=True))
            far_entities.append(pad_list(CONTEXT_LENGTH, far, from_left=False))

            polygon_size = 2
            target_coord.append(construct_spatial_grid(eval(line[4]), polygon_size))
            near_entities_coord.append(construct_spatial_grid(eval(line[6]), polygon_size))
            far_entities_coord.append(construct_spatial_grid(eval(line[7]), polygon_size))

            target_string.append(pad_list(TARGET_LENGTH, eval(line[5]), from_left=True))

            if counter % BATCH_SIZE == 0:
                for collection in [near_words, far_words, near_entities, far_entities, target_string]:
                    for x in collection:
                        for i, w in enumerate(x):
                            if w in w2i:
                                x[i] = w2i[w]
                            else:
                                x[i] = w2i[UNKNOWN]
                if train:
                    yield ([np.asarray(near_words), np.asarray(far_words), np.asarray(near_entities),
                            np.asarray(far_entities), np.asarray(near_entities_coord),
                            np.asarray(far_entities_coord), np.asarray(target_coord), np.asarray(target_string)], np.asarray(labels))
                else:
                    yield ([np.asarray(near_words), np.asarray(far_words), np.asarray(near_entities),
                            np.asarray(far_entities), np.asarray(near_entities_coord),
                            np.asarray(far_entities_coord), np.asarray(target_coord), np.asarray(target_string)])

                near_words, far_words, near_entities, far_entities, labels = [], [], [], [], []
                near_entities_coord, far_entities_coord, target_coord, target_string = [], [], [], []

        if len(labels) > 0:  # This block is only ever entered at the end to yield the final few samples. (< BATCH_SIZE)
            for collection in [near_words, far_words, near_entities, far_entities, target_string]:
                for x in collection:
                    for i, w in enumerate(x):
                        if w in w2i:
                            x[i] = w2i[w]
                        else:
                            x[i] = w2i[UNKNOWN]

            if train:
                yield ([np.asarray(near_words), np.asarray(far_words), np.asarray(near_entities),
                        np.asarray(far_entities), np.asarray(near_entities_coord), np.asarray(far_entities_coord),
                        np.asarray(target_coord), np.asarray(target_string)], np.asarray(labels))
            else:
                yield ([np.asarray(near_words), np.asarray(far_words), np.asarray(near_entities),
                        np.asarray(far_entities), np.asarray(near_entities_coord), np.asarray(far_entities_coord),
                        np.asarray(target_coord), np.asarray(target_string)])


def generate_strings_from_file(path):
    """Returns Y, NAME and CONTEXT"""
    while True:
        for line in codecs.open(path, "r", encoding="utf-8"):
            line = line.strip().split("\t")
            context = u" ".join(eval(line[2])) + u"*E*" + u" ".join(eval(line[5])) + u"*E*" + u" ".join(eval(line[3]))
            yield ((float(line[0]), float(line[1])), u" ".join(eval(line[5])).strip(), context)


def compute_embedding_distances(W, dim, polygon_size):
    store = []
    W = np.reshape(W, (int(180 / polygon_size), int(360 / polygon_size), dim))
    for row in W:
        store_col = []
        for column in row:
            col_vector = []
            for r in W:
                for c in r:
                    col_vector.append(euclidean(column, c))
            store_col.append(col_vector)
        store.append(store_col)
    return store


def compute_pixel_similarity(polygon_size):
    distances_p = compute_embedding_distances(cPickle.load(open("data/W.pkl")), 801, polygon_size)

    store = []
    for r in range(int(180 / polygon_size)):
        store_c = []
        for c in range(int(360 / polygon_size)):
            store_c.append((r, c))
        store.append(store_c)

    distances_g = compute_embedding_distances(np.array(store), 2, polygon_size)

    correlations = []
    for p, g in zip(distances_p, distances_g):
        for cp, cg in zip(p, g):
            correlations.append(np.corrcoef(cp, cg))

    cPickle.dump(correlations, open(u"data/correlations.pkl", "w"))


def filter_wiktor():
    wiktor = set()
    for line in codecs.open(u"data/eval_wiki_gold.txt", "r", encoding="utf-8"):
        wiktor.add(line)
    print(len(wiktor))
    for line in codecs.open(u"../data/train_wiki_uniform.txt", "r", encoding="utf-8"):
        if line in wiktor:
            print line


def training_map(polygon_size):
    coordinates = []
    for f in [u"../data/train_wiki_uniform.txt"]:
        training_file = codecs.open(f, "r", encoding="utf-8")
        for line in training_file:
            line = line.strip().split("\t")
            coordinates.append((float(line[0]), float(line[1]), 0))
    c = construct_spatial_grid(coordinates, polygon_size)
    c = np.reshape(c, (int(180 / polygon_size), int(360 / polygon_size)))
    visualise_2D_grid(c, "Training Map", log=True)


def generate_arrays_from_file_loc(path, train=True):
    """"""
    while True:
        training_file = codecs.open(path, "r", encoding="utf-8")
        counter = 0
        polygon_size = 2
        labels, target_coord = [], []
        for line in training_file:
            counter += 1
            line = line.strip().split("\t")
            labels.append(construct_spatial_grid([(float(line[0]), float(line[1]), 0)], 2))
            target_coord.append(construct_loc2vec(eval(line[4]), eval(line[6]), eval(line[7]), polygon_size))
            print list(target_coord[-1])

            if counter % BATCH_SIZE == 0:
                if train:
                    yield ([np.asarray(target_coord)], np.asarray(labels))
                else:
                    yield ([np.asarray(target_coord)])

                labels = []
                target_coord = []

        if len(labels) > 0:  # This block is only ever entered at the end to yield the final few samples. (< BATCH_SIZE)
            if train:
                yield ([np.asarray(target_coord)], np.asarray(labels))
            else:
                yield ([np.asarray(target_coord)])


# ----------------------------------------------INVOKE METHODS HERE----------------------------------------------------
# training_map()
# visualise_2D_grid(construct_2D_grid(get_coordinates(sqlite3.connect('../data/geonames.db').cursor(), u"washington")), "image")
# print get_coordinates(sqlite3.connect('../data/geonames.db').cursor(), u"china")
# generate_training_data()
# generate_evaluation_data(corpus="lgl", file_name="")
# index = coord_to_index((-6.43, -172.32), True)
# print(index, index_to_coord(index))
# generate_vocabulary()
# for word in generate_names_from_file("data/eval_lgl.txt"):
#     print word.strip()
# print(get_coordinates(sqlite3.connect('../data/geonames.db').cursor(), u"norway"))

# conn = sqlite3.connect('../data/geonames.db')
# c = conn.cursor()
# c.execute("INSERT INTO GEO VALUES (?, ?)", (u"darfur", u"[(13.5, 23.5, 0), (13.0, 25.0, 10000), (44.05135, -94.83804, 106)]"))
# c.execute("DELETE FROM GEO WHERE name = 'darfur'")
# conn.commit()

# populate_sql()

# for line in codecs.open("data/eval_wiki.txt", "r", encoding="utf-8"):
#     line = line.strip().split("\t")
#     print line[0], line[1]
#     x = construct_2D_grid(eval(line[4]), use_pop=True)
#     print(get_non_zero_entries(x))
#     visualise_2D_grid(x, line[6] + u" target.")
#     x = construct_2D_grid([(float(line[0]), float(line[1]), 0)], use_pop=False)
#     print(get_non_zero_entries(x))
#     visualise_2D_grid(x, line[6] + u" label.")
#     x = construct_2D_grid(eval(line[5]), use_pop=False)
#     print(get_non_zero_entries(x))
#     visualise_2D_grid(x, line[6] + u" entities.")


# c = Counter(c)
# counts = []
# for key in c.most_common():
#     counts.append(key[1])
# print(len(c)/4462.0)
#
# y_pos = np.arange(len(counts))
# plt.bar(y_pos, counts, align='center', alpha=0.5)
# plt.ylabel('Counts')
# plt.title('Toponym Counts')
# plt.show()

# counter = 0
# out = codecs.open("data/test.txt", "w", encoding="utf-8")
# for line in codecs.open("data/wiki.txt", "r", encoding="utf-8"):
#     if counter % 3 == 0:
#         out.write(line)
#     counter += 1

# correlations = [x[0][1] for x in cPickle.load(open("data/correlations.pkl"))]
# correlations = [x[0][1] for x in correlations]
# minimum = min(correlations)
# ran = max(correlations) - minimum
# correlations = [x + ran for x in correlations]
# correlations = np.reshape(np.array(correlations), ((180 / GRID_SIZE), (360 / GRID_SIZE)))
# correlations = np.rot90((np.rot90(correlations)))
# visualise_2D_grid(correlations, "GeoPixelSpatialCorrelation")
