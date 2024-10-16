from country_workspace.versioning.management.manager import Manager


def run_scripts():
    m = Manager()
    m.forward(m.max_version)
