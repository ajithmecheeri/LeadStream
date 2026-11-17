"""Print an Ed25519 key pair as single-line env values for JWT_PRIVATE_KEY / JWT_PUBLIC_KEY."""

from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

key = Ed25519PrivateKey.generate()
priv = key.private_bytes(
    serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption()
).decode()
pub = (
    key.public_key()
    .public_bytes(serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo)
    .decode()
)
print("JWT_PRIVATE_KEY=" + priv.strip().replace("\n", "\\n"))
print("JWT_PUBLIC_KEY=" + pub.strip().replace("\n", "\\n"))
