import type {
  Attribute,
  Html,
  HtmlBuilder,
  TextareaAttribute,
} from "foldkit/html";

import { cx } from "./cx.js";
import type { Child } from "./html.js";
import type { Translator } from "./i18n.js";

const inputLook =
  "w-full px-3 py-2 text-base sm:text-sm rounded-lg border border-border aria-invalid:border-danger bg-bg-secondary text-foreground placeholder:text-foreground-muted disabled:opacity-50 disabled:cursor-not-allowed";

const textareaLook =
  "w-full px-3 py-2 rounded-lg border border-border aria-invalid:border-danger bg-bg-secondary text-foreground placeholder:text-foreground-muted disabled:opacity-50 disabled:cursor-not-allowed text-base sm:text-sm leading-relaxed";

const selectLook =
  "w-full px-3 py-2 text-base sm:text-sm rounded-lg border border-border aria-invalid:border-danger bg-bg-secondary text-foreground disabled:opacity-50 disabled:cursor-not-allowed";

const labelLook =
  "block text-sm font-medium text-foreground-secondary first-letter:uppercase";

export type Described = Readonly<{
  errors?: readonly string[];
  help?: string;
  id: string;
}>;

export const helpId = (field: Described) =>
  field.help === undefined || (field.errors ?? []).length > 0
    ? undefined
    : `${field.id}_help`;

const invalid = <Message>(field: Described, h: HtmlBuilder<Message>) => {
  const describedBy = helpId(field);

  return [
    ...((field.errors ?? []).length > 0 ? [h.AriaInvalid(true)] : []),
    ...(describedBy === undefined ? [] : [h.AriaDescribedBy(describedBy)]),
  ];
};

export const label = <Message>(
  options: Readonly<{
    asLegend?: boolean;
    forId?: string;
    required?: boolean;
    text: Child;
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
) => {
  const children: readonly Child[] = [
    options.text,
    ...(options.required === true
      ? [
          h.span([h.Class("text-danger"), h.AriaHidden(true)], ["*"]),
          h.span(
            [h.Class("sr-only")],
            [`(${options.translator.t("required")})`]
          ),
        ]
      : []),
  ];

  return options.asLegend === true
    ? h.legend([h.Class(labelLook)], children)
    : h.label(
        [
          ...(options.forId === undefined ? [] : [h.For(options.forId)]),
          h.Class(labelLook),
        ],
        children
      );
};

export const helpAndErrors = <Message>(
  field: Described,
  h: HtmlBuilder<Message>
): Html[] => {
  const describedBy = helpId(field);

  return [
    ...(describedBy === undefined || field.help === undefined
      ? []
      : [
          h.p(
            [h.Id(describedBy), h.Class("text-xs mt-1 text-foreground-muted")],
            [field.help]
          ),
        ]),
    ...(field.errors ?? []).map((error) =>
      h.p([h.Class("text-xs mt-1 text-danger")], [error])
    ),
  ];
};

export type TextFieldOptions<Message> = Described &
  Readonly<{
    attributes?: readonly Attribute<Message>[];
    autocomplete?: string;
    disabled?: boolean;
    name: string;
    placeholder?: string;
    required?: boolean;
    type?: string;
    value: string;
  }>;

export const textInput = <Message>(
  options: TextFieldOptions<Message>,
  h: HtmlBuilder<Message>
) =>
  h.input([
    h.Type(options.type ?? "text"),
    h.Class(inputLook),
    h.Name(options.name),
    h.Id(options.id),
    h.Value(options.value),
    ...(options.placeholder === undefined
      ? []
      : [h.Placeholder(options.placeholder)]),
    ...(options.autocomplete === undefined
      ? []
      : [h.Autocomplete(options.autocomplete)]),
    ...(options.required === true ? [h.Required(true)] : []),
    ...(options.disabled === true ? [h.Disabled(true)] : []),
    ...invalid(options, h),
    ...(options.attributes ?? []),
  ]);

export type TextareaOptions<Message> = Described &
  Readonly<{
    attributes?: readonly TextareaAttribute<Message>[];
    name: string;
    placeholder?: string;
    required?: boolean;
    rows?: number;
    value: string;
  }>;

export const textareaInput = <Message>(
  options: TextareaOptions<Message>,
  h: HtmlBuilder<Message>
) =>
  h.textarea([
    h.Class(textareaLook),
    h.Id(options.id),
    h.Name(options.name),
    h.Rows(options.rows ?? 4),
    h.Value(options.value),
    ...(options.placeholder === undefined
      ? []
      : [h.Placeholder(options.placeholder)]),
    ...(options.required === true ? [h.Required(true)] : []),
    ...invalid(options, h),
    ...(options.attributes ?? []),
  ]);

export type SelectOption = Readonly<{ label: string; value: string }>;

export type SelectOptions<Message> = Described &
  Readonly<{
    attributes?: readonly Attribute<Message>[];
    disabled?: boolean;
    groups?: readonly Readonly<{
      label: string;
      options: ReadonlyArray<SelectOption>;
    }>[];
    name: string;
    options?: readonly SelectOption[];
    required?: boolean;
    selected: string;
  }>;

export const selectInput = <Message>(
  options: SelectOptions<Message>,
  h: HtmlBuilder<Message>
) => {
  const option = (choice: SelectOption) =>
    h.option(
      [
        h.Value(choice.value),
        ...(choice.value === options.selected ? [h.Selected(true)] : []),
      ],
      [choice.label]
    );

  return h.select(
    [
      h.Class(selectLook),
      h.Id(options.id),
      h.Name(options.name),
      ...(options.required === true ? [h.Required(true)] : []),
      ...(options.disabled === true ? [h.Disabled(true)] : []),
      ...invalid(options, h),
      ...(options.attributes ?? []),
    ],
    options.groups === undefined
      ? (options.options ?? []).map(option)
      : options.groups.map((group) =>
          group.label === ""
            ? h.empty
            : h.optgroup([h.LabelAttr(group.label)], group.options.map(option))
        )
  );
};

export const field = <Message>(
  options: Readonly<{
    control: Html;
    described: Described;
    label: Child;
    layout?: "horizontal" | "vertical";
    required?: boolean;
    translator: Translator;
  }>,
  h: HtmlBuilder<Message>
) => {
  const fieldLabel = label(
    {
      forId: options.described.id,
      text: options.label,
      translator: options.translator,
      ...(options.required === undefined ? {} : { required: options.required }),
    },
    h
  );

  const controls = [options.control, ...helpAndErrors(options.described, h)];

  return h.div(
    [
      h.Class(
        cx(
          "flex gap-y-0.5 not-last:mb-4",
          options.layout === "horizontal" ? "max-sm:flex-col" : "flex-col"
        )
      ),
    ],
    options.layout === "horizontal"
      ? [
          h.div([h.Class("sm:w-1/3 sm:pt-2")], [fieldLabel]),
          h.div([h.Class("sm:w-2/3")], controls),
        ]
      : [fieldLabel, ...controls]
  );
};

export type CheckboxOptions<Message> = Readonly<{
  ariaLabel?: string;
  attributes?: readonly Attribute<Message>[];
  checked: boolean;
  disabled?: boolean;
  id?: string;
  name?: string;
  size?: string;
  value?: string;
}>;

export const checkboxInput = <Message>(
  options: CheckboxOptions<Message>,
  h: HtmlBuilder<Message>
) =>
  h.input([
    h.Type("checkbox"),
    h.Class(
      cx(
        options.size ?? "w-4 h-4",
        "rounded border border-border accent-primary shrink-0 cursor-pointer outline-none focus-visible:ring-2 focus-visible:ring-primary/50 focus-visible:ring-offset-2"
      )
    ),
    ...(options.id === undefined ? [] : [h.Id(options.id)]),
    ...(options.name === undefined ? [] : [h.Name(options.name)]),
    ...(options.value === undefined ? [] : [h.Value(options.value)]),
    ...(options.ariaLabel === undefined
      ? []
      : [h.AriaLabel(options.ariaLabel)]),
    h.Checked(options.checked),
    ...(options.disabled === true ? [h.Disabled(true)] : []),
    ...(options.attributes ?? []),
  ]);

export const checkboxField = <Message>(
  options: CheckboxOptions<Message> & Readonly<{ label: Child }>,
  h: HtmlBuilder<Message>
) =>
  h.label(
    [h.Class("inline-flex items-center cursor-pointer select-none")],
    [
      checkboxInput(options, h),
      h.span([h.Class("ml-2 text-sm text-foreground")], [options.label]),
    ]
  );

export const checkboxToggle = <Message>(
  options: CheckboxOptions<Message> & Readonly<{ label: Child }>,
  h: HtmlBuilder<Message>
) =>
  h.label(
    [
      h.Class(
        "inline-flex items-center gap-2 px-3 py-2 rounded-lg bg-bg-tertiary text-sm font-medium text-foreground whitespace-nowrap cursor-pointer select-none transition-colors duration-150 hover:bg-border has-checked:bg-primary-light has-checked:text-primary"
      ),
    ],
    [checkboxInput(options, h), h.span([], [options.label])]
  );

export const radio = <Message>(
  options: Readonly<{
    attributes?: readonly Attribute<Message>[];
    checked: boolean;
    label: Child;
    name: string;
    value: string;
  }>,
  h: HtmlBuilder<Message>
) =>
  h.label(
    [h.Class("flex items-center gap-2 text-sm text-foreground cursor-pointer")],
    [
      h.input([
        h.Type("radio"),
        h.Class(
          "w-4 h-4 border-border accent-primary focus:ring-2 focus:ring-offset-2"
        ),
        h.Name(options.name),
        h.Value(options.value),
        h.Checked(options.checked),
        ...(options.attributes ?? []),
      ]),
      h.span([], [options.label]),
    ]
  );

export type Choice<Message> = Readonly<{
  attributes?: readonly Attribute<Message>[];
  checked: boolean;
  id: string;
  label: Child;
  value: string;
}>;

export const choiceGroup = <Message>(
  options: Described &
    Readonly<{
      choices: readonly Choice<Message>[];
      inputType: "checkbox" | "radio";
      name: string;
      toggle?: boolean;
    }>,
  h: HtmlBuilder<Message>
) => {
  const hasErrors = (options.errors ?? []).length > 0;
  const toggle = options.toggle === true;

  return h.div(
    [
      h.Class(cx("mt-2", toggle ? "flex flex-wrap gap-2" : "space-y-1")),
      ...invalid(options, h),
    ],
    options.choices.map((choice) => {
      const input = h.input([
        h.Type(options.inputType),
        h.Id(choice.id),
        h.Name(options.name),
        h.Value(choice.value),
        h.Class(
          toggle
            ? "absolute inset-0 opacity-0 cursor-pointer"
            : cx(
                "w-4 h-4 rounded border accent-primary focus:ring-1 focus:ring-offset-0",
                hasErrors ? "border-danger" : "border-border"
              )
        ),
        h.Checked(choice.checked),
        ...(choice.attributes ?? []),
      ]);

      return toggle
        ? h.label(
            [
              h.Class(
                "relative inline-flex items-center px-3 py-2 rounded-lg bg-bg-tertiary text-sm font-medium text-foreground whitespace-nowrap cursor-pointer select-none transition-colors duration-150 hover:bg-border has-checked:bg-primary-light has-checked:text-primary has-focus-visible:ring-2 has-focus-visible:ring-primary/50 has-focus-visible:ring-offset-2"
              ),
            ],
            [input, h.span([], [choice.label])]
          )
        : h.label(
            [h.Class("flex items-center cursor-pointer")],
            [
              input,
              h.span([h.Class("ml-2 text-sm text-foreground")], [choice.label]),
            ]
          );
    })
  );
};

export const formErrors = <Message>(
  errors: readonly string[],
  h: HtmlBuilder<Message>
) =>
  errors.map((error) =>
    h.div([h.Class("alert alert-danger text-sm mb-4")], [error])
  );
