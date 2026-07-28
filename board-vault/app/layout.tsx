import type { Metadata } from "next";
import { headers } from "next/headers";
import "../frontend/styles.css";

export async function generateMetadata(): Promise<Metadata> {
  const requestHeaders = await headers();
  const host = requestHeaders.get("x-forwarded-host") ?? requestHeaders.get("host") ?? "localhost:3000";
  const protocol = requestHeaders.get("x-forwarded-proto") ?? (host.startsWith("localhost") ? "http" : "https");
  const origin = `${protocol}://${host}`;
  return {
    title: "单板金样｜多厂家金样数据管理",
    description: "单板金样录入、自动比对、冲突处理与审批入库平台。",
    openGraph: { title: "单板金样", description: "上传 · 比对 · 审批", images: [`${origin}/og-golden-sample.png`] },
    twitter: { card: "summary_large_image", title: "单板金样", description: "上传 · 比对 · 审批", images: [`${origin}/og-golden-sample.png`] },
  };
}

export default function RootLayout({ children }: Readonly<{ children: React.ReactNode }>) {
  return <html lang="zh-CN"><body>{children}</body></html>;
}
