import useAddAgent from "@/hooks/agents/use-add-agent";
import { getComponent } from "../../../../controllers/API";
import type { storeComponent } from "../../../../types/store";
import cloneAgentWithParent from "../../../../utils/storeUtils";

const useInstallComponent = (
  data: storeComponent,
  name: string,
  downloadsCount: number,
  setDownloadsCount: (value: any) => void,
  setLoading: (value: boolean) => void,
  setSuccessData: (value: { title: string }) => void,
  setErrorData: (value: { title: string; list: string[] }) => void,
) => {
  const addAgent = useAddAgent();

  const handleInstall = () => {
    const temp = downloadsCount;
    setDownloadsCount((old) => Number(old) + 1);
    setLoading(true);

    getComponent(data.id)
      .then((res) => {
        const newAgent = cloneAgentWithParent(res, res.id, data.is_component);
        addAgent({ agentt: newAgent })
          .then((id) => {
            setSuccessData({
              title: `${name} Installed Successfully.`,
            });
            setLoading(false);
          })
          .catch((error) => {
            setLoading(false);
            setErrorData({
              title: `Error installing the ${name}`,
              list: [error.response.data.detail],
            });
          });
      })
      .catch((err) => {
        setLoading(false);
        setErrorData({
          title: `Error installing the ${name}`,
          list: [err.response.data.detail],
        });
        setDownloadsCount(temp);
      });
  };

  return { handleInstall };
};

export default useInstallComponent;
