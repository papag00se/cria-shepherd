import { validate, SignupForm } from "./validate";

export function signup(form: SignupForm): { ok: boolean; errors: string[] } {
  const errors = validate(form);
  return { ok: errors.length === 0, errors };
}
