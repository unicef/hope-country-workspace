from country_workspace.models import OcrRun, Rdp

from country_workspace.rdp.policy import ActionCheck


class OcrActionPolicy:
    def __init__(self, rdp: Rdp) -> None:
        self.rdp = rdp

    @property
    def is_open(self) -> bool:
        return self.rdp.status in {Rdp.PushStatus.PENDING, Rdp.PushStatus.FAILURE}

    @property
    def has_ocr_run(self) -> bool:
        return OcrRun.objects.filter(rdp_id=self.rdp.pk).exists()

    def is_ocr_visible(self) -> bool:
        return self.is_open

    def ocr_check(self) -> ActionCheck:
        if not self.is_open:
            return ActionCheck(False, f"RDP: can not run OCR in status={self.rdp.status}")
        if self.has_ocr_run:
            return ActionCheck(False, "RDP: OCR has already been run for this RDP.")
        return ActionCheck(True)


def get_ocr_policy(rdp: Rdp) -> OcrActionPolicy:
    if (policy := getattr(rdp, "_ocr_policy", None)) is None:
        policy = OcrActionPolicy(rdp)
        rdp._ocr_policy = policy
    return policy
