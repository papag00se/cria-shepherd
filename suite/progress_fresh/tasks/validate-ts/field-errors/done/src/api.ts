import { validate, SignupForm } from "./validate";

export type FieldErrors = Record<string, string[]>;

export function signup(form: SignupForm): { ok: boolean; errors: FieldErrors } {
  const errors: FieldErrors = {};
  for (const msg of validate(form)) {
    const field = msg.split(":")[0];
    (errors[field] ??= []).push(msg);
  }
  return { ok: Object.keys(errors).length === 0, errors };
}
