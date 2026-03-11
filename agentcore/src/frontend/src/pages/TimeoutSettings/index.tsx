import { useEffect, useMemo, useState } from "react";
import { Save, RotateCcw } from "lucide-react";
import { useTranslation } from "react-i18next";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";
import { Label } from "@/components/ui/label";
import { Switch } from "@/components/ui/switch";
import {
  Select,
  SelectContent,
  SelectItem,
  SelectTrigger,
  SelectValue,
} from "@/components/ui/select";
import Loading from "@/components/ui/loading";
import {
  useGetTimeoutSettings,
  type TimeoutSetting,
} from "@/controllers/API/queries/config/use-get-timeout-settings";
import { usePutTimeoutSettings } from "@/controllers/API/queries/config/use-put-timeout-settings";
import useAlertStore from "@/stores/alertStore";

export default function TimeoutSettings() {
  const { t } = useTranslation();
  const [settings, setSettings] = useState<TimeoutSetting[]>([]);
  const [originalSettings, setOriginalSettings] = useState<TimeoutSetting[]>([]);
  const [hasChanges, setHasChanges] = useState(false);

  const { data, isLoading, isError } = useGetTimeoutSettings();
  const { mutate: saveSettings, isPending } = usePutTimeoutSettings();
  const setSuccessData = useAlertStore((state) => state.setSuccessData);
  const setErrorData = useAlertStore((state) => state.setErrorData);

  const normalizedSettings = useMemo(
    () =>
      (data ?? []).map((item) => ({
        ...item,
        value: item.value ?? "",
        unit: item.unit ?? "",
        units: item.units ?? [],
      })),
    [data],
  );

  useEffect(() => {
    setSettings(normalizedSettings);
    setOriginalSettings(normalizedSettings);
    setHasChanges(false);
  }, [normalizedSettings]);

  const handleValueChange = (id: string, newValue: string) => {
    setSettings((prev) =>
      prev.map((setting) =>
        setting.id === id ? { ...setting, value: newValue } : setting
      )
    );
    setHasChanges(true);
  };

  const handleUnitChange = (id: string, newUnit: string) => {
    setSettings((prev) =>
      prev.map((setting) =>
        setting.id === id ? { ...setting, unit: newUnit } : setting
      )
    );
    setHasChanges(true);
  };

  const handleSwitchChange = (id: string, checked: boolean) => {
    setSettings((prev) =>
      prev.map((setting) =>
        setting.id === id ? { ...setting, checked } : setting
      )
    );
    setHasChanges(true);
  };

  const handleSave = () => {
    saveSettings(settings, {
      onSuccess: () => {
        setOriginalSettings(settings);
        setHasChanges(false);
        setSuccessData({ title: t("Timeout settings saved successfully") });
      },
      onError: () => {
        setErrorData({ title: t("Failed to save timeout settings.") });
      },
    });
  };

  const handleReset = () => {
    setSettings(originalSettings);
    setHasChanges(false);
  };

  return (
    <div className="flex h-full w-full flex-col overflow-auto">
      <div className="flex items-center justify-between border-b px-8 py-6">
        <div>
          <div className="mb-2 flex items-center gap-3">
            <h1 className="text-2xl font-semibold">{t("Platform Configurations")}</h1>
          </div>
          <p className="text-sm text-muted-foreground">
            {t("Configure system timeouts and session management")}
          </p>
        </div>
        <div className="flex items-center gap-3">
          <Button
            variant="outline"
            onClick={handleReset}
            disabled={!hasChanges || isLoading || isPending}
            className="gap-2"
          >
            <RotateCcw className="h-4 w-4" />
            {t("Reset to Defaults")}
          </Button>
          <Button
            variant="default"
            onClick={handleSave}
            disabled={!hasChanges || isLoading || isPending}
            className="gap-2"
          >
            <Save className="h-4 w-4" />
            {t("Save Changes")}
          </Button>
        </div>
      </div>

      <div className="flex-1 overflow-auto p-8">
        {isLoading && (
          <div className="flex h-full w-full items-center justify-center">
            <Loading />
          </div>
        )}
        {isError && !isLoading && (
          <div className="mb-4 rounded-md border border-destructive/20 bg-destructive/5 px-4 py-3 text-sm text-destructive">
            {t("Failed to load timeout settings from database.")}
          </div>
        )}
        {!isLoading && (
          <div className="w-full px-2 lg:px-4 xl:px-6">
            <h2 className="mb-6 text-lg font-semibold">{t("Timeouts")}</h2>

            <div className="overflow-hidden rounded-lg border border-border bg-card">
              <table className="w-full">
                <thead>
                  <tr className="border-b border-border bg-muted/50">
                    <th className="px-6 py-4 text-left text-sm font-medium text-muted-foreground">
                      {t("Setting")}
                    </th>
                    <th className="px-6 py-4 text-left text-sm font-medium text-muted-foreground">
                      {t("Value")}
                    </th>
                    <th className="px-6 py-4 text-left text-sm font-medium text-muted-foreground">
                      {t("Unit")}
                    </th>
                    <th className="px-6 py-4 text-left text-sm font-medium text-muted-foreground">
                      {t("Description")}
                    </th>
                  </tr>
                </thead>
                <tbody className="divide-y divide-border">
                  {settings.map((setting) => (
                    <tr key={setting.id} className="hover:bg-muted/50">
                      <td className="px-6 py-4">
                        <Label className="font-medium">{setting.label}</Label>
                      </td>

                      <td className="px-6 py-4">
                        {setting.type === "input" ? (
                          <Input
                            type="number"
                            value={setting.value}
                            onChange={(e) =>
                              handleValueChange(setting.id, e.target.value)
                            }
                            className="w-24 bg-background"
                            min="0"
                          />
                        ) : (
                          <Switch
                            checked={setting.checked}
                            onCheckedChange={(checked) =>
                              handleSwitchChange(setting.id, checked)
                            }
                          />
                        )}
                      </td>

                      <td className="px-6 py-4">
                        {setting.units.length > 0 ? (
                          <Select
                            value={setting.unit}
                            onValueChange={(value) =>
                              handleUnitChange(setting.id, value)
                            }
                          >
                            <SelectTrigger className="w-24 bg-background">
                              <SelectValue />
                            </SelectTrigger>
                            <SelectContent>
                              {setting.units.map((unit) => (
                                <SelectItem key={unit} value={unit}>
                                  {unit}
                                </SelectItem>
                              ))}
                            </SelectContent>
                          </Select>
                        ) : (
                          <span className="text-muted-foreground">-</span>
                        )}
                      </td>

                      <td className="px-6 py-4">
                        <span className="text-sm text-muted-foreground">
                          {setting.description}
                        </span>
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>

            <div className="mt-6 rounded-lg border border-border bg-blue-50 p-4 dark:bg-blue-950/20">
              <div className="flex gap-3">
                <div className="flex h-5 w-5 flex-shrink-0 items-center justify-center rounded-full bg-blue-500 text-white">
                  <span className="text-xs font-bold">i</span>
                </div>
                <div className="text-sm">
                  <p className="font-medium text-blue-900 dark:text-blue-100">
                    {t("Important")}
                  </p>
                  <p className="mt-1 text-blue-800 dark:text-blue-200">
                    {t(
                      "Changes are global and are applied from the database at login and token refresh. Active users will pick up new values on their next token refresh cycle.",
                    )}
                  </p>
                </div>
              </div>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}
