from country_workspace.versioning.synclog import create_default_synclog, removes_default_synclog


class Scripts:
    operations = [(create_default_synclog, removes_default_synclog)]
