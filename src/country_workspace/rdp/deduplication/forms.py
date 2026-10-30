from country_workspace.rdp.forms import ThresholdConfigForm


class BiometricDeduplicationConfigForm(ThresholdConfigForm):
    """Configure the biometric deduplication review threshold."""

    rate_help_text = "Findings per 100 individuals in the RDP."
