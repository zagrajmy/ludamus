declare module "markdown-actions" {
  export function toggleBold(textarea: HTMLTextAreaElement): void;
  export function toggleItalic(textarea: HTMLTextAreaElement): void;
  export function insertLink(
    textarea: HTMLTextAreaElement,
    options?: { text?: string; url?: string },
  ): void;
}
