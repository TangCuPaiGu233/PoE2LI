import type { Metadata } from "next";
import SiteNav from "@/components/SiteNav";
import "./globals.css";

export const metadata: Metadata = {
  title: "流放漓 PoE2LI - PoE2 智能工具站",
  description: "粘贴 PoB 分享码，获取 AI 生成的构建攻略",
};

export default function RootLayout({
  children,
}: Readonly<{
  children: React.ReactNode;
}>) {
  return (
    <html lang="zh-CN">
      <body className="ninja-page">
        <SiteNav />
        {children}
      </body>
    </html>
  );
}
