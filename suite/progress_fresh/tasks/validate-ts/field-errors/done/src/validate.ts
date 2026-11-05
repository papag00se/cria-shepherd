export interface SignupForm {
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
