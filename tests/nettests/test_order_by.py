"""
Copyright (c) .NET Foundation and Contributors.
Copyright (c) FlpIt
SPDX-License-Identifier: MIT

Tests for the FlpIt ``take`` operator.

Ported to pytest/Python from the .NET Runtime System.Linq OrderByTests.cs:
https://github.com/dotnet/runtime/blob/main/src/libraries/System.Linq/tests/OrderByTests.cs

Original source attribution: .NET Foundation / dotnet/runtime, MIT License.
This file is an independent Python port adapted to FlpIt's API and semantics.
"""
import time
import gc
import pytest
import random
import locale
import contextlib
from functools import cmp_to_key

# HYPOTHESE: Das bereitgestellte Fixture. 'flp' muss importiert sein.
# import flp
# @pytest.fixture(params=[flp.it, flp.lst], ids=["FlpIt", "FlpList"])
# def flp_type(request):
#     return request.param

# --- Hilfsklassen & Mocks ---

def bad_comparer_1(x, y):
    return 1

def bad_comparer_2(x, y):
    return -1

def extreme_comparer(x, y):
    if x == y:
        return 0
    if x < y:
        return -2147483648  # int.MinValue
    return 2147483647   # int.MaxValue

def run_once_generator(seq):
    """Simuliert C# RunOnce() - iteriert genau einmal und ist dann erschöpft."""
    yield from seq

def number_range_guaranteed_not_collection_type(start, count):
    return (i for i in range(start, start + count))

def force_not_collection(seq):
    return (x for x in seq)

@contextlib.contextmanager
def thread_culture_change(culture_string):
    """
    HYPOTHESE: Simuliert ThreadCultureChange.
    Achtung: locale.setlocale ändert den Zustand im gesamten Python-Prozess
    und ist nicht thread-safe. Unter Linux/Windows können die genauen Strings abweichen.
    """
    saved_locale = locale.setlocale(locale.LC_COLLATE)
    try:
        # Fallback auf C/Standard, wenn OS den String (z.B. 'da_DK.UTF-8') nicht kennt.
        try:
            locale.setlocale(locale.LC_COLLATE, culture_string)
        except locale.Error:
            pass
        yield
    finally:
        locale.setlocale(locale.LC_COLLATE, saved_locale)


# --- Tests ---

def test_SameResultsRepeatCallsIntQuery(flp_type):
    # from x1 ... from x2 ... select new { a1 = x1, a2 = x2 }
    q = [{"a1": x1, "a2": x2}
         for x1 in [1, 6, 0, -1, 3]
         for x2 in [55, 49, 9, -100, 24, 25]]

    # HYPOTHESE: .then_by() existiert in der flp-API
    res1 = list(flp_type(q).order_by(lambda e: e["a1"]).then_by(lambda f: f["a2"]))
    res2 = list(flp_type(q).order_by(lambda e: e["a1"]).then_by(lambda f: f["a2"]))
    assert res1 == res2

def test_SameResultsRepeatCallsStringQuery(flp_type):
    q = [{"a1": x1, "a2": x2}
         for x1 in [55, 49, 9, -100, 24, 25, -1, 0]
         for x2 in ["!@#$%^", "C", "AAA", "", None, "Calling Twice", "SoS", ""]
         if x2] # where !string.IsNullOrEmpty(x2)

    res1 = list(flp_type(q).order_by(lambda e: e["a1"]))
    res2 = list(flp_type(q).order_by(lambda e: e["a1"]))
    assert res1 == res2

def test_SourceEmpty(flp_type):
    source = []
    assert list(flp_type(source).order_by(lambda e: e)) == []

def test_OrderedCount(flp_type):
    source = random.sample(range(20), 20) # Shuffle
    assert flp_type(source).order_by(lambda i: i).count() == 20

def test_SurviveBadComparerAlwaysReturnsNegative(flp_type):
    pytest.skip("comparer not yet supported")
    source = [1]
    expected = [1]
    assert list(flp_type(source).order_by(lambda e: e, comparer=cmp_to_key(bad_comparer_2))) == expected

def test_KeySelectorReturnsNull(flp_type):
    source = [None, None, None]
    expected = [None, None, None]
    assert list(flp_type(source).order_by(lambda e: e)) == expected

def test_ElementsAllSameKey(flp_type):
    source = [9, 9, 9, 9, 9, 9]
    expected = [9, 9, 9, 9, 9, 9]
    assert list(flp_type(source).order_by(lambda e: e)) == expected

def test_KeySelectorCalled(flp_type):
    source = [
        {"Name": "Tim", "Score": 90},
        {"Name": "Robert", "Score": 45},
        {"Name": "Prakash", "Score": 99}
    ]
    expected = [
        {"Name": "Prakash", "Score": 99},
        {"Name": "Robert", "Score": 45},
        {"Name": "Tim", "Score": 90}
    ]
    # C# übergibt null als Comparer
    assert list(flp_type(source).order_by(lambda e: e["Name"])) == expected

def test_FirstAndLastAreDuplicatesCustomComparer(flp_type):
    source = ["Prakash", "Alpha", "dan", "DAN", "Prakash"]
    expected = ["Alpha", "dan", "DAN", "Prakash", "Prakash"]
    # HYPOTHESE: StringComparer.OrdinalIgnoreCase wird durch str.casefold abgebildet
    assert list(flp_type(source).order_by(lambda e: e.casefold())) == expected

def test_RunOnce(flp_type):
    source = ["Prakash", "Alpha", "dan", "DAN", "Prakash"]
    expected = ["Alpha", "dan", "DAN", "Prakash", "Prakash"]
    assert list(flp_type(run_once_generator(source)).order_by(lambda e: e.casefold())) == expected

def test_FirstAndLastAreDuplicatesNullPassedAsComparer(flp_type):
    source = [5, 1, 3, 2, 5]
    expected = [1, 2, 3, 5, 5]
    assert list(flp_type(source).order_by(lambda e: e)) == expected

def test_SourceReverseOfResultNullPassedAsComparer(flp_type):
    source = [100, 30, 9, 5, 0, -50, -75, None]
    expected = [None, -75, -50, 0, 5, 9, 30, 100]

    # HYPOTHESE: flp sortiert None/Null wie C# nach ganz vorne.
    # In nativem Python wirft None < int einen TypeError. flp muss dies intern handhaben.
    assert list(flp_type(source).order_by(lambda e: e)) == expected

def test_SameKeysVerifySortStable(flp_type):
    source = [
        {"Name": "Tim", "Score": 90},
        {"Name": "Robert", "Score": 90},
        {"Name": "Prakash", "Score": 90},
        {"Name": "Jim", "Score": 90},
        {"Name": "John", "Score": 90},
        {"Name": "Albert", "Score": 90},
    ]
    expected = list(source) # Identische Reihenfolge erwartet
    assert list(flp_type(source).order_by(lambda e: e["Score"])) == expected

def test_OrderedToArray(flp_type):
    source = [{"Name": n, "Score": 90} for n in ["Tim", "Robert", "Prakash", "Jim", "John", "Albert"]]
    expected = list(source)
    # HYPOTHESE: .to_array() oder .to_list() existiert. In Python ist list() der Standardweg.
    assert list(flp_type(source).order_by(lambda e: e["Score"]).to_list()) == expected

def test_EmptyOrderedToArray(flp_type):
    assert list(flp_type([]).order_by(lambda e: e).to_list()) == []

def test_OrderedToList(flp_type):
    source = [{"Name": n, "Score": 90} for n in ["Tim", "Robert", "Prakash", "Jim", "John", "Albert"]]
    expected = list(source)
    assert list(flp_type(source).order_by(lambda e: e["Score"]).to_list()) == expected

def test_EmptyOrderedToList(flp_type):
    assert list(flp_type([]).order_by(lambda e: e).to_list()) == []

def test_SurviveBadComparerAlwaysReturnsPositive(flp_type):
    pytest.skip("comparer not yet supported")
    source = [1]
    expected = [1]
    assert list(flp_type(source).order_by(lambda e: e, comparer=cmp_to_key(bad_comparer_1))) == expected

def test_OrderByExtremeComparer(flp_type):
    pytest.skip("comparer not yet supported")
    out_of_order = [7, 1, 0, 9, 3, 5, 4, 2, 8, 6]
    expected = list(range(10))
    assert list(flp_type(out_of_order).order_by(lambda i: i, comparer=cmp_to_key(extreme_comparer))) == expected

def test_NullSource(flp_type):
    source = None
    with pytest.raises(Exception): # C# wirft ArgumentNullException.
        flp_type(source).order_by(lambda i: i)

def test_NullKeySelector(flp_type):
    key_selector = None
    with pytest.raises(Exception):
        flp_type([]).order_by(key_selector)

def test_FirstOnOrdered(flp_type):
    assert flp_type(random.sample(range(10), 10)).order_by(lambda i: i).first() == 0
    assert flp_type(random.sample(range(10), 10)).order_by_descending(lambda i: i).first() == 9
    assert flp_type(random.sample(range(100), 100)).order_by_descending(lambda i: len(str(i))).then_by(lambda i: i).first() == 10

def test_FirstOnEmptyOrderedThrows(flp_type):
    with pytest.raises(Exception): # C# wirft InvalidOperationException
        flp_type([]).order_by(lambda i: i).first()

def test_FirstWithPredicateOnOrdered(flp_type):
    order_by = flp_type(random.sample(range(10), 10)).order_by(lambda i: i)
    order_by_descending = flp_type(random.sample(range(10), 10)).order_by_descending(lambda i: i)

    counter = {"val": 0}

    def pred1(i): counter["val"] += 1; return True
    counter["val"] = 0
    assert order_by.first(pred1) == 0
    assert counter["val"] == 1

    def pred2(i): counter["val"] += 1; return i == 9
    counter["val"] = 0
    assert order_by.first(pred2) == 9
    assert counter["val"] == 10

    def pred3(i): counter["val"] += 1; return False
    counter["val"] = 0
    with pytest.raises(Exception):
        order_by.first(pred3)
    assert counter["val"] == 10

    counter["val"] = 0
    assert order_by_descending.first(pred1) == 9
    assert counter["val"] == 1

    def pred4(i): counter["val"] += 1; return i == 0
    counter["val"] = 0
    assert order_by_descending.first(pred4) == 0
    assert counter["val"] == 10

    counter["val"] = 0
    with pytest.raises(Exception):
        order_by_descending.first(pred3)
    assert counter["val"] == 10


def test_FirstOrDefaultOnOrdered(flp_type):
    assert flp_type(random.sample(range(10), 10)).order_by(lambda i: i).first_or_default(0) == 0
    assert flp_type(random.sample(range(10), 10)).order_by_descending(lambda i: i).first_or_default(0) == 9
    assert flp_type(random.sample(range(100), 100)).order_by_descending(lambda i: len(str(i))).then_by(lambda i: i).first_or_default(0) == 10
    assert flp_type([]).order_by(lambda i: i).first_or_default(0) == 0


def test_FirstOrDefaultWithPredicateOnOrdered(flp_type):
    order_by = flp_type(random.sample(range(10), 10)).order_by(lambda i: i)
    order_by_descending = flp_type(random.sample(range(10), 10)).order_by_descending(lambda i: i)

    counter = {"val": 0}

    def pred1(i): counter["val"] += 1; return True
    counter["val"] = 0
    assert order_by.first_or_default(0, pred1) == 0
    assert counter["val"] == 1

    def pred2(i): counter["val"] += 1; return i == 9
    counter["val"] = 0
    assert order_by.first_or_default(0, pred2) == 9
    assert counter["val"] == 10

    def pred3(i): counter["val"] += 1; return False
    counter["val"] = 0
    assert order_by.first_or_default(0, pred3) is 0
    assert counter["val"] == 10

    counter["val"] = 0
    assert order_by_descending.first_or_default(0, pred1) == 9
    assert counter["val"] == 1

    def pred4(i): counter["val"] += 1; return i == 0
    counter["val"] = 0
    assert order_by_descending.first_or_default(0, pred4) == 0
    assert counter["val"] == 10

    counter["val"] = 0
    assert order_by_descending.first_or_default(0, pred3) == 0
    assert counter["val"] == 10

def test_LastOnOrdered(flp_type):
    assert flp_type(random.sample(range(10), 10)).order_by(lambda i: i).last() == 9
    assert flp_type(random.sample(range(10), 10)).order_by_descending(lambda i: i).last() == 0
    assert flp_type(random.sample(range(100), 100)).order_by(lambda i: len(str(i))).then_by_descending(lambda i: i).last() == 10

def test_LastOnOrderedMatchingCases(flp_type):
    pytest.skip("last_or_default needs to be implemented")
    boxed_ints = [0, 1, 2, 9, 1, 2, 3, 9, 4, 5, 7, 8, 9, 0, 1]

    assert boxed_ints[12] is flp_type(boxed_ints).order_by(lambda o: o).last()
    assert boxed_ints[12] is flp_type(boxed_ints).order_by(lambda o: o).last_or_default()
    assert boxed_ints[12] is flp_type(boxed_ints).order_by(lambda o: o).last(lambda o: o % 2 == 1)
    assert boxed_ints[12] is flp_type(boxed_ints).order_by(lambda o: o).last_or_default(lambda o: o % 2 == 1)

def test_LastOnEmptyOrderedThrows(flp_type):
    with pytest.raises(Exception):
        flp_type([]).order_by(lambda i: i).last()

def test_LastOrDefaultOnOrdered(flp_type):
    pytest.skip("last_or_default needs to be implemented")
    assert flp_type(random.sample(range(10), 10)).order_by(lambda i: i).last_or_default() == 9
    assert flp_type(random.sample(range(10), 10)).order_by_descending(lambda i: i).last_or_default() == 0
    assert flp_type(random.sample(range(100), 100)).order_by(lambda i: len(str(i))).then_by_descending(lambda i: i).last_or_default() == 10
    assert flp_type([]).order_by(lambda i: i).last_or_default() is None

def test_EnumeratorDoesntContinue(flp_type):
    seq = random.sample(list(number_range_guaranteed_not_collection_type(0, 3)), 3)
    enumerator = iter(flp_type(seq).order_by(lambda i: i))

    for _ in enumerator:
        pass

    with pytest.raises(StopIteration):
        next(enumerator)

def test_OrderByIsCovariantTestWithCast(flp_type):
    # Python hat keine Typparameter. Die Logik überprüft lediglich das korrekte Chainen.
    ordered = flp_type(range(100)).select(str).order_by(len)
    covariant_ordered = ordered
    covariant_ordered = covariant_ordered.then_by(lambda i: i)

    expected = list(flp_type(range(100)).select(str).order_by(len).then_by(lambda i: i))
    assert list(covariant_ordered) == expected

def test_OrderByIsCovariantTestWithAssignToArgument(flp_type):
    ordered = flp_type(range(100)).select(str).order_by(len)
    covariant_ordered = ordered.then_by_descending(lambda i: i)

    expected = list(flp_type(range(100)).select(str).order_by(len).then_by_descending(lambda i: i))
    assert list(covariant_ordered) == expected

def test_CanObtainFromCovariantIOrderedQueryable(flp_type):
    # HYPOTHESE: AsQueryable() wird in flp ggf. ignoriert oder durchgeladen.
    ordered = flp_type(range(100)).select(str).order_by(len)
    ordered = ordered.then_by(lambda i: i)

    expected = list(flp_type(range(100)).select(str).order_by(len).then_by(lambda i: i))
    assert list(ordered) == expected

def test_SortsLargeAscendingEnumerableCorrectly(flp_type):
    items = 1_000_000
    expected = list(number_range_guaranteed_not_collection_type(0, items))
    unordered = flp_type(expected).select(lambda i: i)
    ordered = unordered.order_by(lambda i: i)
    assert list(ordered) == expected

def test_SortsLargeDescendingEnumerableCorrectly(flp_type):
    items = 1_000_000
    expected = list(number_range_guaranteed_not_collection_type(0, items))
    unordered = flp_type(expected).select(lambda i: items - i - 1)
    ordered = unordered.order_by(lambda i: i)
    assert list(ordered) == expected

@pytest.mark.parametrize("items", [0, 1, 2, 3, 8, 16, 1024, 4096, 1_000_000])
def test_SortsRandomizedEnumerableCorrectly(flp_type, items):
    random.seed(42)
    randomized = [random.randint(0, 2147483647) for _ in range(items)]
    randomized.append(None)

    # don't get interrupted while
    gc.collect()
    gc.disable()
    start = time.perf_counter()

    ordered = list(flp_type(force_not_collection(randomized)).order_by(lambda i: i))

    elapsed = time.perf_counter() - start
    gc.enable()

    # pure sort time should never exceed 1s
    assert elapsed < 0.7 # not part of the original test

    # randomized.sort(key=lambda x: (x is not None, x))

    # Separate, sort the integers, and join them back together
    ints = sorted(x for x in randomized if x is not None)
    nones = [None] * (len(randomized) - len(ints))

    # Combine them (mimics .NET: Nones at the beginning)
    randomized = nones + ints

    assert ordered == randomized

@pytest.mark.parametrize("source", [
    [1],
    [1, 2],
    [2, 1],
    [1, 2, 3, 4, 5],
    [5, 4, 3, 2, 1],
    [4, 3, 2, 1, 5, 9, 8, 7, 6],
    [2, 4, 6, 8, 10, 5, 3, 7, 1, 9]
])
def test_TakeOne(flp_type, source):
    count = 0
    for x in flp_type(source).order_by(lambda i: i).take(1):
        count += 1
        assert x == min(source)
    assert count == 1

def test_CultureOrderBy(flp_type):
    source = ["Apple0", "\uFFFDble0", "Apple1", "\uFFFDble1", "Apple2", "\uFFFDble2"]

    # Python locales erfordern vom Betriebssystem installierte Pakete (z.B. da_DK.UTF-8)
    dk_locale = "da_DK.UTF-8" if locale.normalize("da_DK") != "da_DK" else "da_DK"
    au_locale = "en_AU.UTF-8" if locale.normalize("en_AU") != "en_AU" else "en_AU"

    with thread_culture_change(dk_locale):
        result_dk = sorted(source, key=cmp_to_key(locale.strcoll))

    with thread_culture_change(au_locale):
        result_au = sorted(source, key=cmp_to_key(locale.strcoll))

    with thread_culture_change(dk_locale):
        check = list(flp_type(source).order_by(lambda x: x))
        # Da flp das interne Sortierverhalten diktiert, ist dieser Assert fragil.
        assert check == result_dk

    with thread_culture_change(au_locale):
        check = list(flp_type(source).order_by(lambda x: x))
        assert check == result_au

    # IEnumerator Test mit Context Switch
    with thread_culture_change(dk_locale):
        s = iter(flp_type(source).order_by(lambda x: x))
        with thread_culture_change(au_locale):
            idx = 0
            for item in s:
                assert item == result_au[idx] # flp müsste hier lazily in "au" sortieren
                idx += 1

    with thread_culture_change(au_locale):
        s = iter(flp_type(source).order_by(lambda x: x))
        with thread_culture_change(dk_locale):
            try:
                first_item = next(s)
                move_next = True
            except StopIteration:
                move_next = False

            assert move_next is True

            with thread_culture_change(au_locale):
                idx = 0
                if move_next:
                    assert first_item == result_dk[idx]
                    idx += 1
                    for item in s:
                        assert item == result_dk[idx]
                        idx += 1

def test_CultureOrderByElementAt(flp_type):
    source = ["Apple0", "\uFFFDble0", "Apple1", "\uFFFDble1", "Apple2", "\uFFFDble2"]

    dk_locale = "da_DK.UTF-8" if locale.normalize("da_DK") != "da_DK" else "da_DK"
    au_locale = "en_AU.UTF-8" if locale.normalize("en_AU") != "en_AU" else "en_AU"

    with thread_culture_change(dk_locale):
        result_dk = sorted(source, key=cmp_to_key(locale.strcoll))
    with thread_culture_change(au_locale):
        result_au = sorted(source, key=cmp_to_key(locale.strcoll))

    delay_sorted_source = flp_type(source).order_by(lambda x: x)

    for i in range(len(source)):
        with thread_culture_change(dk_locale):
            assert delay_sorted_source.element_at(i) == result_dk[i]
        with thread_culture_change(au_locale):
            assert delay_sorted_source.element_at(i) == result_au[i]

def test_OrderBy_FirstLast_MatchesArray(flp_type):
    arrays = [
        [1],
        [1, 1],
        [1, 2, 1],
        [1, 2, 1, 3],
        [2, 1, 3, 1, 4]
    ]

    for objects in arrays:
        # assert X is Y (Referenzgleichheit in C# über Assert.Same)
        # In Python werden primitive Integers intern als Singleton zwischengespeichert,
        # Listen-Element-Referenzen können mit `is` geprüft werden.
        first_a = flp_type(objects).order_by(lambda x: x).first()
        first_b = list(flp_type(objects).order_by(lambda x: x))[0]
        assert first_a is first_b

        last_a = flp_type(objects).order_by(lambda x: x).last()
        last_b = list(flp_type(objects).order_by(lambda x: x))[-1]
        assert last_a is last_b