from country_workspace.versioning.synclog import create_default_synclog, removes_default_synclog


class Version:
    operations = [(create_default_synclog, removes_default_synclog)]
