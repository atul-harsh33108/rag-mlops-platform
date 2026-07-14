import { SignUp } from "@clerk/nextjs";

export default function SignUpPage() {
  return (
    <div className="min-h-[70vh] flex items-center justify-center p-4">
      <SignUp />
    </div>
  );
}