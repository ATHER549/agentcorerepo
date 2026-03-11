import { useMemo, useState } from "react";
import { useTranslation } from "react-i18next";
import { Badge } from "@/components/ui/badge";
import { Button } from "@/components/ui/button";
import Loading from "@/components/ui/loading";
import { Textarea } from "@/components/ui/textarea";
import {
  useGetCurrentRelease,
  useGetReleases,
  usePostBumpRelease,
} from "@/controllers/API/queries/releases";
import useAlertStore from "@/stores/alertStore";

type BumpType = "major" | "minor" | "patch";

const BUMP_OPTIONS: { value: BumpType; label: string; description: string }[] = [
  { value: "major", label: "Major", description: "X+1.0.0 (breaking changes)" },
  { value: "minor", label: "Minor", description: "X.Y+1.0 (new features)" },
  { value: "patch", label: "Patch", description: "X.Y.Z+1 (fixes)" },
];

const ACTIVE_END_DATE = "9999-12-31";

export default function ReleaseManagementPage() {
  const { t } = useTranslation();
  const [bumpType, setBumpType] = useState<BumpType>("patch");
  const [notes, setNotes] = useState("");

  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const { data: currentRelease, isLoading: isLoadingCurrent } = useGetCurrentRelease();
  const { data: releases, isLoading: isLoadingHistory } = useGetReleases();
  const { mutate: bumpRelease, isPending: isBumping } = usePostBumpRelease();

  const isLoading = isLoadingCurrent || isLoadingHistory;
  const history = useMemo(() => releases ?? [], [releases]);

  const handleBump = () => {
    bumpRelease(
      {
        bump_type: bumpType,
        release_notes: notes.trim() || undefined,
      },
      {
        onSuccess: (res) => {
          setNotes("");
          setSuccessData({
            title: t("Release created: {{version}}", { version: res.version }),
          });
        },
        onError: (error: any) => {
          const message =
            error?.response?.data?.detail ||
            t("Failed to create release. Please try again.");
          setErrorData({ title: message });
        },
      },
    );
  };

  return (
    <div className="flex h-full w-full flex-col overflow-hidden">
      <div className="flex flex-shrink-0 items-center justify-between border-b px-8 py-6">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <h1 className="text-2xl font-semibold">{t("Release Management")}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t("Create semantic product releases and track release history windows.")}
          </p>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-8">
        {isLoading ? (
          <div className="flex h-full w-full items-center justify-center">
            <Loading />
          </div>
        ) : (
          <div className="space-y-6">
            <div className="rounded-lg border border-border bg-card p-5">
              <div className="mb-2 text-sm text-muted-foreground">{t("Current Active Release")}</div>
              {currentRelease ? (
                <div className="flex items-center gap-3">
                  <Badge variant="outline" size="sm">
                    {currentRelease.version}
                  </Badge>
                  <span className="text-sm text-muted-foreground">
                    {t("Window")}: {currentRelease.start_date} - {currentRelease.end_date}
                  </span>
                </div>
              ) : (
                <div className="text-sm text-muted-foreground">
                  {t("No active release found. Create the first release below.")}
                </div>
              )}
            </div>

            <div className="rounded-lg border border-border bg-card p-5">
              <h2 className="mb-4 text-lg font-semibold">{t("Create Release")}</h2>
              <div className="mb-4 grid gap-3 md:grid-cols-3">
                {BUMP_OPTIONS.map((option) => (
                  <button
                    key={option.value}
                    type="button"
                    onClick={() => setBumpType(option.value)}
                    className={`rounded-md border px-4 py-3 text-left transition-colors ${
                      bumpType === option.value
                        ? "border-primary bg-primary/10"
                        : "border-border bg-background hover:bg-muted/40"
                    }`}
                  >
                    <div className="font-medium">{t(option.label)}</div>
                    <div className="text-xs text-muted-foreground">{t(option.description)}</div>
                  </button>
                ))}
              </div>
              <div className="mb-4">
                <div className="mb-2 text-sm text-muted-foreground">{t("Release Notes")}</div>
                <Textarea
                  value={notes}
                  onChange={(e) => setNotes(e.target.value)}
                  placeholder={t("What changed in this release?")}
                  rows={4}
                />
              </div>
              <Button onClick={handleBump} disabled={isBumping} className="gap-2">
                {isBumping ? t("Creating...") : t("Create Release")}
              </Button>
            </div>

            <div className="overflow-x-auto rounded-lg border border-border bg-card">
              <table className="w-full">
                <thead>
                  <tr className="border-b bg-muted/40 text-xs text-muted-foreground">
                    <th className="px-4 py-3 text-left font-medium">{t("Version")}</th>
                    <th className="px-4 py-3 text-left font-medium">{t("Start Date")}</th>
                    <th className="px-4 py-3 text-left font-medium">{t("End Date")}</th>
                    <th className="px-4 py-3 text-left font-medium">{t("Status")}</th>
                    <th className="px-4 py-3 text-left font-medium">{t("Notes")}</th>
                  </tr>
                </thead>
                <tbody>
                  {history.length === 0 ? (
                    <tr>
                      <td colSpan={5} className="px-4 py-8 text-center text-sm text-muted-foreground">
                        {t("No releases yet.")}
                      </td>
                    </tr>
                  ) : (
                    history.map((release) => (
                      <tr
                        key={release.id}
                        className="border-b last:border-0 transition-colors hover:bg-muted/30"
                      >
                        <td className="px-4 py-3">
                          <Badge variant="outline" size="sm">
                            {release.version}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-sm">{release.start_date}</td>
                        <td className="px-4 py-3 text-sm">{release.end_date}</td>
                        <td className="px-4 py-3 text-sm">
                          <Badge
                            variant="outline"
                            size="sm"
                            className={
                              release.end_date === ACTIVE_END_DATE
                                ? "border-green-500/50 text-green-600"
                                : ""
                            }
                          >
                            {release.end_date === ACTIVE_END_DATE ? t("Active") : t("Closed")}
                          </Badge>
                        </td>
                        <td className="px-4 py-3 text-sm text-muted-foreground">
                          {release.release_notes || "-"}
                        </td>
                      </tr>
                    ))
                  )}
                </tbody>
              </table>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
