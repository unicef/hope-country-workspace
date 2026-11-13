from country_workspace.rdp.forms import ThresholdConfigForm


class BiographicDeduplicationConfigForm(ThresholdConfigForm):
    """Configure the biographic deduplication review threshold."""

    rate_help_text = "Individuals with duplicates per 100 individuals in the RDP."
