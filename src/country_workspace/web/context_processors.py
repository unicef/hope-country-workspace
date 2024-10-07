from country_workspace.state import state


def current_state(request):
    ret = {"state": state}
    return ret
