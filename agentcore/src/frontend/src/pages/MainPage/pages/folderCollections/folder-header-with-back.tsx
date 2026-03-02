import { ArrowLeft } from "lucide-react";
import { useCustomNavigate } from "@/customization/hooks/use-custom-navigate";
import { useFolderStore } from "@/stores/foldersStore";
import { useParams } from "react-router-dom";

/**
 * Add this component to HomePage to show back button
 * Place it at the top of the page
 */
export default function FolderHeaderWithBack(): JSX.Element {
  const navigate = useCustomNavigate();
  const params = useParams();
  const folders = useFolderStore((state) => state.folders);
  
  const currentFolder = folders?.find((f) => f.id === params.folderId);

  // Only show on folder detail pages
  if (!params.folderId) {
    return <></>;
  }

  return (
    <div className="flex items-center gap-3 border-b px-6 py-3">
      <button
        onClick={() => navigate("/all")}
        className="flex items-center gap-2 rounded-md px-2 py-1 text-sm text-muted-foreground transition-colors hover:bg-accent hover:text-foreground"
      >
        <ArrowLeft className="h-4 w-4" />
        Back to Projects
      </button>
      {currentFolder && (
        <>
          <span className="text-muted-foreground">/</span>
          <h2 className="text-base font-semibold">{currentFolder.name}</h2>
        </>
      )}
    </div>
  );
}