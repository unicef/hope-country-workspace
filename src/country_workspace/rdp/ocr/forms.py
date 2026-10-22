from country_workspace.rdp.forms import ThresholdConfigForm


class OcrConfigForm(ThresholdConfigForm):
    """Configure the OCR review threshold."""

    rate_label = "Findings per 100 individuals with OCR documents"
