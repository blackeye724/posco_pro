"use client";

import { FormEvent, useState } from "react";
import { useRouter } from "next/navigation";
import { AppShell, PageMessage } from "../../components/AppShell";
import { login } from "../../components/api";

export default function LoginPage() {
  const router = useRouter();
  const [notice, setNotice] = useState("");
  const [busy, setBusy] = useState(false);

  async function submit(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setBusy(true);
    const form = new FormData(event.currentTarget);
    try {
      const result = await login(String(form.get("user_id") || ""), String(form.get("password") || ""));
      window.localStorage.setItem("mvp_user_id", result.user_id);
      window.localStorage.setItem("mvp_display_name", result.display_name);
      window.localStorage.setItem("mvp_department", result.department);
      window.localStorage.setItem("mvp_roles", JSON.stringify(result.roles));
      router.push("/");
    } catch (error) {
      setNotice(error instanceof Error ? error.message : "로그인에 실패했습니다.");
    } finally {
      setBusy(false);
    }
  }

  return <AppShell eyebrow="ACCESS / MVP" title="공사비 적정성 검토 로그인"><p className="lead">부서 계정으로 로그인하면 해당 부서의 검토·승인 기능을 사용할 수 있습니다.</p>{notice && <PageMessage tone="danger">{notice}</PageMessage>}<section className="panel login-panel"><form className="login-form" onSubmit={submit}><label htmlFor="login-user-id">아이디<input id="login-user-id" name="user_id" autoComplete="username" placeholder="예: pfc391" required /></label><label htmlFor="login-password">비밀번호<input id="login-password" name="password" type="password" autoComplete="current-password" required /></label><button type="submit" disabled={busy}>{busy ? "로그인 중…" : "로그인"}</button></form><p className="muted-line">개발용 계정은 운영 배포 전에 비밀번호를 변경하고 SSO/MFA로 전환해야 합니다.</p></section></AppShell>;
}
