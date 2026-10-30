import { Result, Schema } from "effect";

export class PluralFormsError extends Schema.TaggedError<PluralFormsError>()(
  "PluralFormsError",
  {
    reason: Schema.String,
  }
) {
  override get message(): string {
    return `Plural-Forms: ${this.reason}`;
  }
}

export interface PluralRule {
  readonly count: number;
  readonly select: (n: number) => number;
}

type Evaluate = (n: number) => number;

interface Token {
  readonly text: string;
  readonly offset: number;
}

const BINARY: ReadonlyArray<
  Readonly<Record<string, (left: number, right: number) => number>>
> = [
  { "||": (left, right) => Number(left !== 0 || right !== 0) },
  { "&&": (left, right) => Number(left !== 0 && right !== 0) },
  {
    "!=": (left, right) => Number(left !== right),
    "==": (left, right) => Number(left === right),
  },
  {
    "<": (left, right) => Number(left < right),
    "<=": (left, right) => Number(left <= right),
    ">": (left, right) => Number(left > right),
    ">=": (left, right) => Number(left >= right),
  },
  { "+": (left, right) => left + right, "-": (left, right) => left - right },
  {
    "%": (left, right) => (right === 0 ? 0 : left % right),
    "*": (left, right) => left * right,
    "/": (left, right) => (right === 0 ? 0 : Math.trunc(left / right)),
  },
];

const tokenize = (
  source: string
): Result.Result<ReadonlyArray<Token>, PluralFormsError> => {
  const tokens: Array<Token> = [];
  const pattern = /\s*(\d+|n|==|!=|<=|>=|&&|\|\||[<>!%*/+\-?:()])/y;
  let position = 0;

  while (source.slice(position).trim() !== "") {
    pattern.lastIndex = position;
    const match = pattern.exec(source);

    if (match === null) {
      const offset =
        position +
        (source.slice(position).length -
          source.slice(position).trimStart().length);

      return Result.fail(
        new PluralFormsError({
          reason: `unexpected \`${source.charAt(offset)}\` at offset ${offset} in \`${source}\``,
        })
      );
    }

    const text = match[1] ?? "";
    tokens.push({ offset: pattern.lastIndex - text.length, text });
    position = pattern.lastIndex;
  }

  return Result.succeed(tokens);
};

const parseExpression = (
  source: string,
  tokens: ReadonlyArray<Token>
): Result.Result<Evaluate, PluralFormsError> => {
  let index = 0;
  const peek = () => tokens[index]?.text;

  const unexpected = () => {
    const token = tokens[index];

    return new PluralFormsError({
      reason:
        token === undefined
          ? `unexpected end of \`${source}\``
          : `unexpected \`${token.text}\` at offset ${token.offset} in \`${source}\``,
    });
  };

  const primary = (): Result.Result<Evaluate, PluralFormsError> => {
    const text = peek();

    if (text === "n") {
      index += 1;

      return Result.succeed((n) => n);
    }

    if (text !== undefined && /^\d+$/.test(text)) {
      index += 1;
      const value = Number(text);

      return Result.succeed(() => value);
    }

    if (text === "!") {
      index += 1;

      return Result.map(
        primary(),
        (operand) => (n) => Number(operand(n) === 0)
      );
    }

    if (text === "-") {
      index += 1;

      return Result.map(primary(), (operand) => (n) => -operand(n));
    }

    if (text === "(") {
      index += 1;
      const inner = ternary();

      if (Result.isFailure(inner) || peek() !== ")") {
        return Result.isFailure(inner) ? inner : Result.fail(unexpected());
      }

      index += 1;

      return inner;
    }

    return Result.fail(unexpected());
  };

  const binary = (level: number): Result.Result<Evaluate, PluralFormsError> => {
    const operators = BINARY[level];

    if (operators === undefined) {
      return primary();
    }

    let left = binary(level + 1);

    while (Result.isSuccess(left)) {
      const text = peek();

      if (text === undefined || !Object.hasOwn(operators, text)) {
        break;
      }

      const apply = operators[text];
      index += 1;
      const right = binary(level + 1);

      if (apply === undefined || Result.isFailure(right)) {
        return Result.isFailure(right) ? right : Result.fail(unexpected());
      }

      const before = left.success;
      const after = right.success;
      left = Result.succeed((n: number) => apply(before(n), after(n)));
    }

    return left;
  };

  const ternary = (): Result.Result<Evaluate, PluralFormsError> => {
    const condition = binary(0);

    if (Result.isFailure(condition) || peek() !== "?") {
      return condition;
    }

    index += 1;
    const whenTrue = ternary();

    if (Result.isFailure(whenTrue)) {
      return whenTrue;
    }

    if (peek() !== ":") {
      return Result.fail(unexpected());
    }

    index += 1;
    const whenFalse = ternary();

    if (Result.isFailure(whenFalse)) {
      return whenFalse;
    }

    const test = condition.success;
    const yes = whenTrue.success;
    const no = whenFalse.success;

    return Result.succeed((n: number) => (test(n) === 0 ? no(n) : yes(n)));
  };

  const whole = ternary();

  if (Result.isSuccess(whole) && index < tokens.length) {
    return Result.fail(unexpected());
  }

  return whole;
};

const settingOf = (header: string, name: string) => {
  for (const part of header.split(";")) {
    const separator = part.indexOf("=");

    if (separator > 0 && part.slice(0, separator).trim() === name) {
      return part.slice(separator + 1).trim();
    }
  }

  return undefined;
};

export const compilePluralForms = (
  header: string
): Result.Result<PluralRule, PluralFormsError> => {
  const nplurals = settingOf(header, "nplurals");
  const expression = settingOf(header, "plural");

  if (nplurals === undefined || !/^\d+$/.test(nplurals)) {
    return Result.fail(
      new PluralFormsError({ reason: `missing nplurals in \`${header}\`` })
    );
  }

  if (expression === undefined) {
    return Result.fail(
      new PluralFormsError({ reason: `missing plural in \`${header}\`` })
    );
  }

  const count = Number(nplurals);

  return Result.flatMap(tokenize(expression), (tokens) =>
    Result.map(parseExpression(expression, tokens), (evaluate) => ({
      count,
      select: (n: number) => evaluate(Math.trunc(Math.abs(n))),
    }))
  );
};
