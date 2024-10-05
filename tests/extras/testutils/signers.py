from django.core.signing import Signer


class PlainSigner(Signer):
    def signature(self, value, key=None):
        return value

    def sign(self, value):
        return value

    def unsign(self, signed_value):
        return signed_value
