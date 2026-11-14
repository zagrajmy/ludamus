import { describe, expect, it } from "@effect/vitest";
import { Base64 } from "effect/encoding";

import {
  IMAGE_TOO_LARGE,
  MAX_IMAGE_BYTES,
  ImageCheck,
  UNSUPPORTED_IMAGE,
  checkImageDataUrl,
} from "../src/panel/uploads.js";

const PNG = Uint8Array.from([
  0x89, 0x50, 0x4e, 0x47, 0x0d, 0x0a, 0x1a, 0x0a, 0, 0, 0, 13,
]);

const GIF = new TextEncoder().encode("GIF87a\u0001\u0000\u0001\u0000");

const dataUrl = (type: string, bytes: Uint8Array) =>
  `data:${type};base64,${Base64.encode(bytes)}`;

describe("cover upload check", () => {
  it("accepts a PNG by its signature, whatever type the browser claimed", () => {
    expect(checkImageDataUrl(dataUrl("application/octet-stream", PNG))).toEqual(
      ImageCheck.Accepted({ bytes: PNG, kind: "png" })
    );
  });

  it("refuses a GIF named as a PNG: the bytes decide, not the name", () => {
    expect(checkImageDataUrl(dataUrl("image/png", GIF))).toEqual(
      ImageCheck.Refused({ msgid: UNSUPPORTED_IMAGE })
    );
  });

  it("refuses one byte over 8 MB before looking at the format", () => {
    const oversize = new Uint8Array(MAX_IMAGE_BYTES + 1);

    oversize.set(PNG);
    expect(checkImageDataUrl(dataUrl("image/png", oversize))).toEqual(
      ImageCheck.Refused({ msgid: IMAGE_TOO_LARGE })
    );
  });

  it("refuses something that is not a base64 data URL at all", () => {
    expect(checkImageDataUrl("https://example.com/cover.png")._tag).toBe(
      "Refused"
    );
    expect(checkImageDataUrl("data:image/png;base64,!!!")._tag).toBe("Refused");
  });
});
