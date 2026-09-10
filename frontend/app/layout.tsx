import type { Metadata } from "next";
import "./globals.css";

export const metadata: Metadata = {
  title: "공사비 적정성 검토 | 광양5 사무동",
  description: "원본 도면·내역서·수량산출서 기반 규칙 검토 및 승인 이력 관리",
};

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="ko"><body>{children}</body></html>;
}
