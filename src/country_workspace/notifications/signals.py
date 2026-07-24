import django.dispatch

# Bitcaster Integration Signals
# Triggered when a batch of data has been successfully imported.
# Expected kwargs: program_id (int), batch_id (int), record_count (int), source (str)
data_imported_signal = django.dispatch.Signal()

# Triggered when validation processing is finished.
# Expected kwargs: program_id (int), validation_scope (str - "program" or "batch"), results (dict)
validation_completed_signal = django.dispatch.Signal()

# Triggered when an RDI push cycle successfully completes.
# Expected kwargs: program_id (int), pushed_count (int)
rdi_push_completed_signal = django.dispatch.Signal()

# Triggered when an RDP push finishes with SUCCESS or FAILURE.
# Expected kwargs: program_id (int), rdp_id (int), status (str)
rdp_push_status_changed_signal = django.dispatch.Signal()
