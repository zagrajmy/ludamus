import {
  AssetRecordType,
  type Editor,
  getHashForString,
  type TLAssetStore,
  type TLUiToastsContextType,
} from "tldraw";

// TODO: images upload to the Worker's R2 bucket once phase 1 step 4 lands
// (docs/rfc/0002-board.md, "Assets"). Until then the board refuses files at
// the door, so nothing is inlined into the shared document as base64.

class UploadsUnavailable extends Error {
  override name = "UploadsUnavailable";
}

export const assetStore: TLAssetStore = {
  resolve: (asset) => asset.props.src,
  upload: () => Promise.reject(new UploadsUnavailable("board: image uploads are not built yet")),
};

export function guardExternalContent(
  editor: Editor,
  { comingSoon, toasts }: { comingSoon: string; toasts: TLUiToastsContextType },
): void {
  editor.registerExternalContentHandler("files", () => {
    toasts.addToast({ severity: "info", title: comingSoon });
  });
  // NOTE: tldraw's own link handler fetches the pasted page to read its
  // preview, and the site's Content-Security-Policy refuses any host but
  // ours. A pasted link becomes a plain bookmark that names its address.
  editor.registerExternalAssetHandler("url", async ({ url }) => ({
    id: AssetRecordType.createId(getHashForString(url)),
    meta: {},
    props: { description: "", favicon: "", image: "", src: url, title: url },
    type: "bookmark",
    typeName: "asset",
  }));
}
