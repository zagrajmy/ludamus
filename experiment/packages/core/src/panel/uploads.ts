import { Data, Result } from "effect";
import { Base64 } from "effect/encoding";

export const MAX_IMAGE_BYTES = 8 * 1024 * 1024;

export const IMAGE_TOO_LARGE = "Image too large. Maximum size is 8 MB.";

export const UNSUPPORTED_IMAGE =
  "Unsupported image format. Use JPG, PNG, WebP, or AVIF.";

export type ImageKind = "avif" | "jpeg" | "png" | "webp";

export const IMAGE_SUFFIXES: Readonly<Record<ImageKind, string>> = {
  avif: ".avif",
  jpeg: ".jpg",
  png: ".png",
  webp: ".webp",
};

const startsWith = (bytes: Uint8Array, prefix: readonly number[], offset = 0) =>
  prefix.every((byte, index) => bytes[offset + index] === byte);

const ascii = (text: string): readonly number[] => [...new TextEncoder().encode(text)];

export const imageKindOf = (bytes: Uint8Array): ImageKind | null => {
  if (startsWith(bytes, [0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a])) {
    return "png";
  }

  if (startsWith(bytes, [0xff, 0xd8, 0xff])) {
    return "jpeg";
  }

  if (startsWith(bytes, ascii("RIFF")) && startsWith(bytes, ascii("WEBP"), 8)) {
    return "webp";
  }

  return startsWith(bytes, ascii("ftypavif"), 4) ? "avif" : null;
};

export type ImageCheck = Data.TaggedEnum<{
  Accepted: { readonly bytes: Uint8Array; readonly kind: ImageKind };
  Refused: { readonly msgid: string };
}>;

export const ImageCheck = Data.taggedEnum<ImageCheck>();

export const checkImageDataUrl = (dataUrl: string): ImageCheck => {
  const comma = dataUrl.indexOf(",");
  const header = comma === -1 ? "" : dataUrl.slice(0, comma);

  if (!header.startsWith("data:") || !header.endsWith(";base64")) {
    return ImageCheck.Refused({ msgid: UNSUPPORTED_IMAGE });
  }

  const decoded = Base64.decode(dataUrl.slice(comma + 1));

  if (Result.isFailure(decoded)) {
    return ImageCheck.Refused({ msgid: UNSUPPORTED_IMAGE });
  }

  const bytes = decoded.success;

  if (bytes.length > MAX_IMAGE_BYTES) {
    return ImageCheck.Refused({ msgid: IMAGE_TOO_LARGE });
  }

  const kind = imageKindOf(bytes);

  return kind === null
    ? ImageCheck.Refused({ msgid: UNSUPPORTED_IMAGE })
    : ImageCheck.Accepted({ bytes, kind });
};
