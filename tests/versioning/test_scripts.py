from country_workspace.versioning.management.manager import Manager


def test_forward_backward():
    m = Manager()
    m.forward()
    m.forward()
    m.backward(1)
    m.zero()
