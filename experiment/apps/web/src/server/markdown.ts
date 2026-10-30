import { Marked } from "marked";

const renderer = new Marked({ async: false, gfm: true });

const entities: Readonly<Record<string, string>> = {
  "&#39;": "'",
  "&amp;": "&",
  "&gt;": ">",
  "&lt;": "<",
  "&quot;": '"',
};

export const renderMarkdown = (source: string) =>
  renderer.parse(source, { async: false });

export const markdownToPlainText = (source: string) =>
  source === ""
    ? ""
    : renderMarkdown(source)
        .replace(/<[^>]*>/gu, "")
        .replace(
          /&(?:#39|amp|gt|lt|quot);/gu,
          (entity) => entities[entity] ?? entity
        )
        .trim();
