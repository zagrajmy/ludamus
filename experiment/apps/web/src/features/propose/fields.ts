import type { FieldError, FormErrors } from "@zagrajmy/core/contracts";
import type { Html, HtmlBuilder } from "foldkit/html";

import { EnhanceWriteIn } from "../../client/propose/command.js";
import type { FieldView } from "../../client/propose/flags.js";
import type { ProposeMessage } from "../../client/propose/message.js";
import type { PostedForm } from "../../client/propose/model.js";
import { cx } from "../../ui/cx.js";
import type { Translator } from "../../ui/i18n.js";
import { icon } from "../../ui/icon.js";
import { visibilityIcon } from "../../ui/visibility.js";

export type H = HtmlBuilder<ProposeMessage>;

const INPLACE_BASE =
  "[font:inherit] [color:inherit] [letter-spacing:inherit] bg-transparent border-0 rounded-md px-1.5 py-0.5 -mx-1.5 -my-0.5 max-sm:text-base transition-[background-color,box-shadow] duration-150 hover:duration-0 hover:bg-foreground/5 focus:outline-none focus:ring-2 focus:ring-primary/40 placeholder:text-foreground-muted not-focus:outline-1 not-focus:outline-warm-400 dark:not-focus:outline-neutral-600 aria-invalid:outline-danger";

const INPLACE_LOOKS = {
  fit: "not-focus:outline-dotted field-sizing-content min-w-24 max-w-full",
  number:
    "not-focus:outline-dashed field-sizing-content min-w-10 text-center tabular-nums [appearance:textfield] [&::-webkit-inner-spin-button]:appearance-none [&::-webkit-outer-spin-button]:appearance-none",
  select: "not-focus:outline-dashed min-w-10 cursor-pointer",
  text: "not-focus:outline-dashed block w-[calc(100%+0.75rem)]",
  textarea:
    "not-focus:outline-dashed block w-[calc(100%+0.75rem)] [@supports(field-sizing:content)]:resize-none field-sizing-content placeholder-shown:min-h-[3lh]",
} as const;

export const inplaceLook = (
  look: keyof typeof INPLACE_LOOKS,
  unit = false
): string =>
  cx(INPLACE_BASE, INPLACE_LOOKS[look], unit && "pr-[calc(0.375rem+1ch)]");

export const INPUT_LOOK =
  "w-full px-3 py-2 text-base sm:text-sm rounded-lg border border-border aria-invalid:border-danger bg-bg-secondary text-foreground placeholder:text-foreground-muted disabled:opacity-50 disabled:cursor-not-allowed";

const SELECT_LOOK =
  "w-full px-3 py-2 text-base sm:text-sm rounded-lg border border-border aria-invalid:border-danger bg-bg-secondary text-foreground disabled:opacity-50 disabled:cursor-not-allowed";

export const errorText = (translator: Translator, error: FieldError): string =>
  error.plural === null
    ? translator.t(error.msgid, error.vars)
    : translator.n(error.msgid, error.plural.msgid, error.plural.count, {
        ...error.vars,
      });

export const errorsOf = (
  errors: FormErrors,
  translator: Translator,
  key: string
): readonly string[] =>
  (errors[key] ?? []).map((error) => errorText(translator, error));

export const lastValue = (draft: PostedForm, name: string): string =>
  draft[name]?.at(-1) ?? "";

export const optional = <A>(condition: boolean, value: A): readonly A[] =>
  condition ? [value] : [];

export const fieldLabel = (
  options: Readonly<{
    field: FieldView;
    withName: boolean;
    visibilityBadge: boolean;
    translator: Translator;
  }>,
  h: H
): readonly Html[] => {
  const { field, translator } = options;

  const shown =
    options.withName && field.name !== "" ? field.name : field.question;

  return [
    h.span(
      [],
      [
        field.icon === null
          ? h.empty
          : icon(
              field.icon,
              {
                class:
                  "inline size-[1.4cap] mr-1 align-[-0.2cap] text-foreground-muted",
              },
              h
            ),
        shown,
        ...(field.isRequired
          ? [
              h.span([h.Class("text-danger"), h.AriaHidden(true)], ["*"]),
              h.span([h.Class("sr-only")], [`(${translator.t("required")})`]),
            ]
          : []),
        options.visibilityBadge
          ? visibilityIcon({ isPublic: field.isPublic, translator }, h)
          : h.empty,
      ]
    ),
    options.withName && field.name !== "" && field.name !== field.question
      ? h.span([h.Class("font-normal text-foreground-muted")], [field.question])
      : h.empty,
  ];
};

const LABEL_LOOK =
  "flex flex-wrap items-baseline justify-between gap-x-4 w-full text-sm font-medium text-foreground-secondary first-letter:uppercase";

export const describedBy = (ids: readonly string[]) => {
  const joined = ids.filter((id) => id !== "").join(" ");

  return joined === "" ? [] : [joined];
};

export const choiceList = (
  options: Readonly<{
    name: string;
    hasErrors: boolean;
    choices: readonly Readonly<{
      id: string;
      label: string;
      value: string;
      checked: boolean;
    }>[];
  }>,
  h: H
) =>
  h.div(
    [
      h.Class("mt-2 space-y-1"),
      ...optional(options.hasErrors, h.AriaInvalid(true)),
    ],
    options.choices.map((choice) =>
      h.label(
        [h.Class("flex items-center cursor-pointer")],
        [
          h.input([
            h.Type("checkbox"),
            h.Id(choice.id),
            h.Name(options.name),
            h.Attribute("value", choice.value),
            h.Class(
              cx(
                "w-4 h-4 rounded border accent-primary focus:ring-1 focus:ring-offset-0",
                options.hasErrors ? "border-danger" : "border-border"
              )
            ),
            ...optional(choice.checked, h.Attribute("checked", "")),
          ]),
          h.span([h.Class("ml-2 text-sm text-foreground")], [choice.label]),
        ]
      )
    )
  );

const textControl = (
  options: Readonly<{
    name: string;
    id: string;
    value: string;
    maxLength: number | null;
    required: boolean;
    hasErrors: boolean;
    describedBy: readonly string[];
    placeholder?: string;
    ariaLabel?: string;
    chips: Readonly<{ remove: string; limit: string }> | null;
  }>,
  h: H
) =>
  h.input([
    h.Type("text"),
    h.Class(INPUT_LOOK),
    h.Name(options.name),
    h.Id(options.id),
    ...optional(
      options.placeholder !== undefined,
      h.Placeholder(options.placeholder ?? "")
    ),
    ...optional(options.value !== "", h.Attribute("value", options.value)),
    ...optional(
      options.maxLength !== null,
      h.Attribute("maxlength", String(options.maxLength))
    ),
    ...optional(options.required, h.Required(true)),
    ...optional(options.hasErrors, h.AriaInvalid(true)),
    ...optional(
      options.ariaLabel !== undefined,
      h.AriaLabel(options.ariaLabel ?? "")
    ),
    ...describedBy(options.describedBy).map((ids) => h.AriaDescribedBy(ids)),
    ...(options.chips === null
      ? []
      : [
          h.DataAttribute("write-in-chips", ""),
          h.DataAttribute("chips-remove-label", options.chips.remove),
          h.DataAttribute("chips-limit-error", options.chips.limit),
        ]),
  ]);

const errorBlock = (id: string, messages: readonly string[], h: H) =>
  messages.length === 0
    ? h.empty
    : h.div(
        [h.Id(id)],
        messages.map((message) =>
          h.p([h.Class("text-sm text-danger")], [message])
        )
      );

export const dynamicField = (
  options: Readonly<{
    field: FieldView;
    prefix: string;
    draft: PostedForm;
    errors: FormErrors;
    translator: Translator;
    visibilityBadge: boolean;
    enhancedWriteIns: readonly string[];
  }>,
  h: H
) => {
  const { field, translator } = options;
  const name = `${options.prefix}_${field.slug}`;
  const inputId = `id_${name}`;
  const customName = `${name}_custom`;
  const customId = `${inputId}_custom`;
  const selected = options.draft[name] ?? [];
  const errors = errorsOf(options.errors, translator, name);
  const customErrors = errorsOf(options.errors, translator, customName);
  const helpId = field.helpHtml === "" ? "" : `${inputId}_help`;
  const errorId = errors.length > 0 ? `${inputId}_error` : "";
  const customErrorId = customErrors.length > 0 ? `${customId}_error` : "";
  const fieldDescribedBy = [helpId, errorId];
  const hasErrors = errors.length > 0;

  const label = (withName: boolean) =>
    fieldLabel(
      { field, translator, visibilityBadge: options.visibilityBadge, withName },
      h
    );

  const main = (): readonly Html[] => {
    if (field.fieldType === "select" && field.isMultiple) {
      return [
        h.fieldset(
          describedBy(fieldDescribedBy).map((ids) => h.AriaDescribedBy(ids)),
          [
            h.legend([h.Class(LABEL_LOOK)], label(true)),
            choiceList(
              {
                choices: field.options.map((option, index) => ({
                  checked: selected.includes(option.value),
                  id: `${inputId}_${String(index)}`,
                  label: option.label,
                  value: option.value,
                })),
                hasErrors,
                name,
              },
              h
            ),
          ]
        ),
      ];
    }

    if (field.fieldType === "select") {
      const current = selected.at(-1) ?? "";

      return [
        h.label([h.For(inputId), h.Class(LABEL_LOOK)], label(true)),
        h.select(
          [
            h.Class(SELECT_LOOK),
            ...optional(hasErrors, h.AriaInvalid(true)),
            h.Id(inputId),
            h.Name(name),
            ...optional(field.controlRequired, h.Required(true)),
            ...describedBy(fieldDescribedBy).map((ids) =>
              h.AriaDescribedBy(ids)
            ),
          ],
          [{ label: "—", value: "" }, ...field.options].map((option) =>
            h.option(
              [
                h.Attribute("value", option.value),
                ...optional(
                  option.value === current,
                  h.Attribute("selected", "")
                ),
              ],
              [option.label]
            )
          )
        ),
      ];
    }

    if (field.fieldType === "checkbox") {
      const checked = selected.some(
        (value) => value !== "" && value !== "false"
      );

      return [
        h.label(
          [h.Class("inline-flex items-center cursor-pointer")],
          [
            h.input([
              h.Type("checkbox"),
              h.Class(
                "w-4 h-4 rounded border border-border accent-primary shrink-0 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2"
              ),
              h.Id(inputId),
              h.Name(name),
              h.Attribute("value", "true"),
              ...describedBy(fieldDescribedBy).map((ids) =>
                h.AriaDescribedBy(ids)
              ),
              ...optional(checked, h.Attribute("checked", "")),
            ]),
            h.span(
              [h.Class("ml-2 text-sm text-foreground first-letter:uppercase")],
              label(false)
            ),
          ]
        ),
      ];
    }

    return [
      h.label([h.For(inputId), h.Class(LABEL_LOOK)], label(true)),
      textControl(
        {
          chips: null,
          describedBy: fieldDescribedBy,
          hasErrors,
          id: inputId,
          maxLength: field.maxLength,
          name,
          required: field.controlRequired,
          value: selected.at(-1) ?? "",
        },
        h
      ),
    ];
  };

  const isChips = field.offersCustom && field.isMultiple;

  const custom = (): readonly Html[] => {
    if (!field.offersCustom) {
      return [];
    }

    const control = textControl(
      {
        ariaLabel: translator.t("Custom value for: %(question)s", {
          question: field.question,
        }),
        chips: isChips
          ? {
              limit: translator.t("This value is too long to add here."),
              remove: translator.t("Remove"),
            }
          : null,
        describedBy: [helpId, customErrorId],
        hasErrors: customErrors.length > 0,
        id: customId,
        maxLength: field.maxLength,
        name: customName,
        placeholder: translator.t("Or type a custom value"),
        required: false,
        value: lastValue(options.draft, customName),
      },
      h
    );

    return [
      isChips
        ? h.div(
            [
              h.DataAttribute("write-in", name),
              h.OnMount(EnhanceWriteIn({ name })),
            ],
            [control]
          )
        : control,
      errorBlock(customErrorId, customErrors, h),
      isChips
        ? h.span(
            [
              h.Class("text-xs text-foreground-muted"),
              h.DataAttribute(
                "chips-hint",
                translator.t("Type a value and press Enter to add it.")
              ),
            ],
            [
              options.enhancedWriteIns.includes(name)
                ? translator.t("Type a value and press Enter to add it.")
                : translator.t("semicolon separated"),
            ]
          )
        : h.empty,
    ];
  };

  return h.div(
    [h.Class("flex flex-col gap-y-1 mb-4"), h.Key(name)],
    [
      ...main(),
      ...custom(),
      helpId === ""
        ? h.empty
        : h.div(
            [
              h.Id(helpId),
              h.Class("text-xs text-foreground-muted"),
              h.InnerHTML(field.helpHtml),
            ],
            []
          ),
      errorBlock(errorId, errors, h),
    ]
  );
};
