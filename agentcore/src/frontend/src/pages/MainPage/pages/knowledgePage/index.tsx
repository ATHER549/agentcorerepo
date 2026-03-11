import { useEffect, useRef, useState } from "react";
import ForwardedIconComponent from "@/components/common/genericIconComponent";
import { SidebarTrigger } from "@/components/ui/sidebar";
import KnowledgeBasesTab from "../filesPage/components/KnowledgeBasesTab";

export const KnowledgePage = () => {
  const [selectedKnowledgeBases, setSelectedKnowledgeBases] = useState<any[]>(
    [],
  );
  const [selectionCount, setSelectionCount] = useState(0);
  const [isShiftPressed, setIsShiftPressed] = useState(false);
  const [searchText, setSearchText] = useState("");
  const containerRef = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const handleKeyDown = (e: KeyboardEvent) => {
      if (e.key === "Shift") {
        setIsShiftPressed(true);
      }
    };

    const handleKeyUp = (e: KeyboardEvent) => {
      if (e.key === "Shift") {
        setIsShiftPressed(false);
      }
    };

    window.addEventListener("keydown", handleKeyDown);
    window.addEventListener("keyup", handleKeyUp);

    return () => {
      window.removeEventListener("keydown", handleKeyDown);
      window.removeEventListener("keyup", handleKeyUp);
    };
  }, []);

  const tabProps = {
    quickFilterText: searchText,
    setQuickFilterText: setSearchText,
    selectedFiles: selectedKnowledgeBases,
    setSelectedFiles: setSelectedKnowledgeBases,
    quantitySelected: selectionCount,
    setQuantitySelected: setSelectionCount,
    isShiftPressed,
  };

  return (
    <div className="flex h-full w-full" data-testid="cards-wrapper" ref={containerRef}>
      <div className="flex h-full w-full flex-col overflow-y-auto transition-all duration-200">
        <div className="flex h-full w-full flex-col xl:container">
          <div className="flex flex-1 flex-col justify-start px-5 pt-10">
            <div className="flex h-full flex-col justify-start">
              <div
                className="flex items-center pb-8 text-xl font-semibold"
                data-testid="mainpage_title"
              >
                <div className="h-7 w-10 transition-all group-data-[open=true]/sidebar-wrapper:md:w-0 lg:hidden">
                  <div className="relative left-0 opacity-100 transition-all group-data-[open=true]/sidebar-wrapper:md:opacity-0">
                    <SidebarTrigger>
                      <ForwardedIconComponent
                        name="PanelLeftOpen"
                        aria-hidden="true"
                      />
                    </SidebarTrigger>
                  </div>
                </div>
                Knowledge
              </div>
              <div className="flex h-full flex-col">
                <KnowledgeBasesTab {...tabProps} />
              </div>
            </div>
          </div>
        </div>
      </div>
    </div>
  );
};

export default KnowledgePage;
