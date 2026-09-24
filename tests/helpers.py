
class Bomb:
    def __bool__(self):
        raise AssertionError("should not be evaluated")

class Falsy:
    def __bool__(self):
        return False

def broken_iterator():
    raise AssertionError("iterator failed before yielding")
    yield

class NoIterList(list):
    def __iter__(self):
        raise AssertionError("should not iterate")