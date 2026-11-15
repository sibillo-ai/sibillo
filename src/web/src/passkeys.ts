// Passkeys through the browser's WebAuthn API, with no library (AUTH-010, ADR-0094).
// The API sends options and takes answers in WebAuthn Level 3's JSON forms,
// whose binary fields are base64url; the browser's API wants ArrayBuffers.

type Json = Record<string, unknown>;

function toBuffer(value: string): ArrayBuffer {
  const base64 = value.replace(/-/g, "+").replace(/_/g, "/").padEnd(Math.ceil(value.length / 4) * 4, "=");
  const bytes = Uint8Array.from(atob(base64), (char) => char.charCodeAt(0));
  return bytes.buffer;
}

function toBase64url(buffer: ArrayBuffer | null): string | null {
  if (buffer === null) return null;
  let text = "";
  for (const byte of new Uint8Array(buffer)) text += String.fromCharCode(byte);
  return btoa(text).replace(/\+/g, "-").replace(/\//g, "_").replace(/=+$/, "");
}

function descriptors(list: unknown): PublicKeyCredentialDescriptor[] | undefined {
  if (!Array.isArray(list)) return undefined;
  return (list as Json[]).map((entry) => ({ ...entry, id: toBuffer(String(entry.id)) }) as PublicKeyCredentialDescriptor);
}

/** Whether this browser can use passkeys at all. */
export function passkeysSupported(): boolean {
  return typeof window !== "undefined" && typeof window.PublicKeyCredential === "function" && !!navigator.credentials;
}

/** Ask the device for a passkey of the user, with the API's `PublicKeyCredentialRequestOptionsJSON`. */
export async function getPasskey(options: Json): Promise<Json> {
  const publicKey = {
    ...options,
    challenge: toBuffer(String(options.challenge)),
    allowCredentials: descriptors(options.allowCredentials),
  } as PublicKeyCredentialRequestOptions;
  const credential = (await navigator.credentials.get({ publicKey })) as PublicKeyCredential | null;
  if (credential === null) throw new DOMException("No passkey was given.", "NotAllowedError");
  const response = credential.response as AuthenticatorAssertionResponse;
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      authenticatorData: toBase64url(response.authenticatorData),
      signature: toBase64url(response.signature),
      userHandle: toBase64url(response.userHandle),
    },
    authenticatorAttachment: credential.authenticatorAttachment,
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}

/** Ask the device to make a passkey, with the API's `PublicKeyCredentialCreationOptionsJSON`. */
export async function createPasskey(options: Json): Promise<Json> {
  const user = options.user as Json;
  const publicKey = {
    ...options,
    challenge: toBuffer(String(options.challenge)),
    user: { ...user, id: toBuffer(String(user.id)) },
    excludeCredentials: descriptors(options.excludeCredentials),
  } as PublicKeyCredentialCreationOptions;
  const credential = (await navigator.credentials.create({ publicKey })) as PublicKeyCredential | null;
  if (credential === null) throw new DOMException("No passkey was made.", "NotAllowedError");
  const response = credential.response as AuthenticatorAttestationResponse;
  return {
    id: credential.id,
    rawId: toBase64url(credential.rawId),
    type: credential.type,
    response: {
      clientDataJSON: toBase64url(response.clientDataJSON),
      attestationObject: toBase64url(response.attestationObject),
      transports: typeof response.getTransports === "function" ? response.getTransports() : [],
    },
    authenticatorAttachment: credential.authenticatorAttachment,
    clientExtensionResults: credential.getClientExtensionResults(),
  };
}
