export interface SignupForm {
  email: string;
  password: string;
  age: number;
}

export function validate(form: SignupForm): string[] {
  const errors: string[] = [];
  if (!form.email.includes("@")) errors.push("email: invalid");
  if (form.password.length < 8) errors.push("password: too short");
  if (!Number.isInteger(form.age) || form.age < 13 || form.age > 120) errors.push("age: out of range");
  return errors;
}
