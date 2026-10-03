"""Generate the key pair for phone notifications. Run once: python scripts/gen_vapid.py"""
import base64

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import ec

b64 = lambda b: base64.urlsafe_b64encode(b).rstrip(b"=").decode()
key = ec.generate_private_key(ec.SECP256R1())
private_raw = key.private_numbers().private_value.to_bytes(32, "big")
public_raw = key.public_key().public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
print("Add these to your host's environment variables:\n")
print("VAPID_PUBLIC_KEY=" + b64(public_raw))
print("VAPID_PRIVATE_KEY=" + b64(private_raw))
