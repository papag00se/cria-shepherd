import { validate, SignupForm } from "./validate";

export function signup(form: SignupForm): { ok: boolean; errors: Record<string, string[]> } {
  const errors: Record<string, string[]> = {};
  for (const msg of validate(form)) {
    const field = msg.split(":")[0];
    (errors[field] ??= []).push(msg);
  }
  return { ok: Object.keys(errors).length === 0, errors };
}
