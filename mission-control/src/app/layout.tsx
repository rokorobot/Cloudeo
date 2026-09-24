import type { Metadata } from "next";
import { Geist, Geist_Mono } from "next/font/google";
import { connection } from "next/server";

import { AppShell } from "@/components/shell/app-shell";
import { Toaster } from "@/components/ui/sonner";
import { TooltipProvider } from "@/components/ui/tooltip";
import { dataSourceFromEnv } from "@/data/mode";
import { WorkOrderDataProvider } from "@/data/provider";
import { UiStateProvider } from "@/state/ui";
import "./globals.css";

const geistSans = Geist({
  variable: "--font-sans",
  subsets: ["latin"],
});

const geistMono = Geist_Mono({
  variable: "--font-geist-mono",
  subsets: ["latin"],
});

export const metadata: Metadata = {
  title: {
    default: "Cloudeo Mission Control",
    template: "%s · Cloudeo",
  },
  description: "Mission control for autonomous work: WorkOrders, evidence and verification.",
};

export default async function RootLayout({ children }: LayoutProps<"/">) {
  // The data source is read per request so one build serves demo or control mode.
  await connection();
  const source = dataSourceFromEnv();
  return (
    <html lang="en" className={`${geistSans.variable} ${geistMono.variable} dark h-full antialiased`}>
      <body>
        <WorkOrderDataProvider source={source}>
          <UiStateProvider>
            <TooltipProvider delayDuration={300}>
              <AppShell>{children}</AppShell>
              <Toaster theme="dark" position="bottom-center" />
            </TooltipProvider>
          </UiStateProvider>
        </WorkOrderDataProvider>
      </body>
    </html>
  );
}
