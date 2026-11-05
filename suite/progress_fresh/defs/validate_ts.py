from suite.progress_fresh.dsl import ed

SEED = {
"src/validate.ts": '''export interface SignupForm {
  email: string;
  password: string;
  age: number;
}

export function validate(form: SignupForm): string[] {
  const errors: string[] = [];
  if (!form.email.includes("@")) errors.push("email: invalid");
  if (form.password.length < 8) errors.push("password: too short");
  return errors;
}
''',
"src/validate.test.ts": '''import { expect, test } from "vitest";
import { validate } from "./validate";

test("accepts a good form", () => {
  expect(validate({ email: "a@b.co", password: "longenough", age: 30 })).toEqual([]);
});

test("rejects a short password", () => {
  expect(validate({ email: "a@b.co", password: "x", age: 30 })).toContain("password: too short");
});
''',
"src/api.ts": '''import { validate, SignupForm } from "./validate";

export function signup(form: SignupForm): { ok: boolean; errors: string[] } {
  const errors = validate(form);
  return { ok: errors.length === 0, errors };
}
''',
}
V = SEED["src/validate.ts"]
T = SEED["src/validate.test.ts"]
A = SEED["src/api.ts"]
TASK = dict(extension=True, name="validate-ts", language="TypeScript", seed=SEED,
unrelated={"src/api.ts": "// thin wrapper used by the HTTP layer\n" + A},
reqs=[
dict(id="age-rule", text="Signup requires age to be an integer between 13 and 120 inclusive; add the rule to validate() with the message \"age: out of range\" and tests for both boundaries on each side.",
 partial={"src/validate.ts": ed(V, ("  return errors;", "  if (form.age < 13) errors.push(\"age: out of range\");\n  return errors;"))},
 done={"src/validate.ts": ed(V, ("  return errors;", "  if (!Number.isInteger(form.age) || form.age < 13 || form.age > 120) errors.push(\"age: out of range\");\n  return errors;")),
       "src/validate.test.ts": T + '''
test.each([12, 121, 30.5])("rejects age %s", (age) => {
  expect(validate({ email: "a@b.co", password: "longenough", age })).toContain("age: out of range");
});

test.each([13, 120])("accepts boundary age %s", (age) => {
  expect(validate({ email: "a@b.co", password: "longenough", age })).toEqual([]);
});
'''}),
dict(id="email-rule", text="The email check only looks for an '@'. Require exactly one '@' with a non-empty local part and a domain containing a dot (so \"a@b\", \"@b.co\" and \"a@@b.co\" are rejected), and test the rejected shapes.",
 partial={"src/validate.ts": ed(V, ('if (!form.email.includes("@"))', 'if (!/^[^@]+@[^@]+$/.test(form.email))'))},
 done={"src/validate.ts": ed(V, ('if (!form.email.includes("@"))', 'if (!/^[^@\\s]+@[^@\\s]+\\.[^@\\s]+$/.test(form.email))')),
       "src/validate.test.ts": T + '''
test.each(["a@b", "@b.co", "a@@b.co", "plain"])("rejects email %s", (email) => {
  expect(validate({ email, password: "longenough", age: 30 })).toContain("email: invalid");
});
'''}),
dict(id="field-errors", text="signup() should return errors grouped by field (e.g. { email: [...], password: [...] }) instead of a flat list, with validate() still returning the flat messages; update signup and its callers' type.",
 partial={"src/api.ts": '''import { validate, SignupForm } from "./validate";

export function signup(form: SignupForm): { ok: boolean; errors: Record<string, string[]> } {
  const errors: Record<string, string[]> = {};
  for (const msg of validate(form)) {
    const field = msg.split(":")[0];
    (errors[field] ??= []).push(msg);
  }
  return { ok: Object.keys(errors).length === 0, errors };
}
'''},
 done={"src/api.ts": '''import { validate, SignupForm } from "./validate";

export type FieldErrors = Record<string, string[]>;

export function signup(form: SignupForm): { ok: boolean; errors: FieldErrors } {
  const errors: FieldErrors = {};
  for (const msg of validate(form)) {
    const field = msg.split(":")[0];
    (errors[field] ??= []).push(msg);
  }
  return { ok: Object.keys(errors).length === 0, errors };
}
''', "src/api.test.ts": '''import { expect, test } from "vitest";
import { signup } from "./api";

test("groups errors by field", () => {
  const r = signup({ email: "nope", password: "x", age: 30 });
  expect(r.ok).toBe(false);
  expect(Object.keys(r.errors).sort()).toEqual(["email", "password"]);
});

test("ok has no errors", () => {
  expect(signup({ email: "a@b.co", password: "longenough", age: 30 })).toEqual({ ok: true, errors: {} });
});
'''}),
])

# supplementary partial-state files (tests/docs the near-miss did write)
_P = {r["id"]: r["partial"] for r in TASK["reqs"]}
_P["age-rule"]["src/validate.test.ts"] = T + '''
test("rejects a child", () => {
  expect(validate({ email: "a@b.co", password: "longenough", age: 12 })).toContain("age: out of range");
});
'''
_P["email-rule"]["src/validate.test.ts"] = T + '''
test.each(["@b.co", "a@@b.co"])("rejects email %s", (email) => {
  expect(validate({ email, password: "longenough", age: 30 })).toContain("email: invalid");
});
'''
