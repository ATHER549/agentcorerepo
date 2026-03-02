import { cloneDeep } from "lodash";
import { useState } from "react";
import useHandleNewValue from "@/CustomNodes/hooks/use-handle-new-value";
import CustomIOFileInput from "@/customization/components/custom-file-input";
import type { AllNodeType } from "@/types/agent";
import ImageViewer from "../../../../components/common/ImageViewer";
import CsvOutputComponent from "../../../../components/core/csvOutputComponent";
import DataOutputComponent from "../../../../components/core/dataOutputComponent";
import InputListComponent from "../../../../components/core/parameterRenderComponent/components/inputListComponent";
import PdfViewer from "../../../../components/core/pdfViewer";
import { Textarea } from "../../../../components/ui/textarea";
import { PDFViewConstant } from "../../../../constants/constants";
import {
  InputOutput,
  IOInputTypes,
  IOOutputTypes,
} from "../../../../constants/enums";
import TextOutputView from "../../../../shared/components/textOutputView";
import useAgentStore from "../../../../stores/agentStore";
import type { IOFieldViewProps } from "../../../../types/components";
import {
  convertValuesToNumbers,
  hasDuplicateKeys,
} from "../../../../utils/reactFlowUtils";
import CsvSelect from "./components/csv-selected";
import IOFileInput from "./components/file-input";
import IoJsonInput from "./components/json-input";
import IOKeyPairInput from "./components/key-pair-input";

export default function IOFieldView({
  type,
  fieldType,
  fieldId,
  left,
}: IOFieldViewProps): JSX.Element | undefined {
  const nodes = useAgentStore((state) => state.nodes);
  const setNode = useAgentStore((state) => state.setNode);
  const agentPool = useAgentStore((state) => state.agentPool);
  const node: AllNodeType | undefined = nodes.find(
    (node) => node.id === fieldId,
  );
  const agentPoolNode = (agentPool[node!.id] ?? [])[
    (agentPool[node!.id]?.length ?? 1) - 1
  ];
  const handleChangeSelect = (e) => {
    if (node) {
      const newNode = cloneDeep(node);
      if (newNode.data.node?.template.separator) {
        newNode.data.node.template.separator.value = e;
        setNode(newNode.id, newNode);
      }
    }
  };

  const [errorDuplicateKey, setErrorDuplicateKey] = useState(false);

  const textOutputValue =
    (agentPool[node!.id] ?? [])[(agentPool[node!.id]?.length ?? 1) - 1]?.data
      .results.text ?? "";

  const { handleOnNewValue } = node?.data.node
    ? useHandleNewValue({
        node: node.data.node,
        nodeId: node.id,
        name: "input_value",
      })
    : { handleOnNewValue: (value: any, options?: any) => {} };

  function handleOutputType() {
    if (!node) return <>"No node found!"</>;
    switch (type) {
      case InputOutput.INPUT:
        switch (fieldType) {
          case IOInputTypes.TEXT:
            return (
              <Textarea
                className={`w-full custom-scroll ${
                  left ? "min-h-32" : "h-full"
                }`}
                placeholder={"Enter text..."}
                value={node.data.node!.template["input_value"].value}
                onChange={(e) => {
                  e.target.value;
                  if (node) {
                    const newNode = cloneDeep(node);
                    newNode.data.node!.template["input_value"].value =
                      e.target.value;
                    setNode(node.id, newNode);
                  }
                }}
              />
            );
          case IOInputTypes.FILE_LOADER:
            return (
              <CustomIOFileInput
                field={node.data.node!.template["file_path"]["value"]}
                updateValue={(e) => {
                  if (node) {
                    const newNode = cloneDeep(node);
                    newNode.data.node!.template["file_path"].value = e;
                    setNode(node.id, newNode);
                  }
                }}
              />
            );

          case IOInputTypes.KEYPAIR:
            return (
              <IOKeyPairInput
                value={node.data.node!.template["input_value"]?.value}
                onChange={(e) => {
                  if (node) {
                    const newNode = cloneDeep(node);
                    newNode.data.node!.template["input_value"].value = e;
                    setNode(node.id, newNode);
                  }
                  const valueToNumbers = convertValuesToNumbers(e);
                  setErrorDuplicateKey(hasDuplicateKeys(valueToNumbers));
                }}
                duplicateKey={errorDuplicateKey}
                isList={node.data.node!.template["input_value"]?.list ?? false}
                isInputField
              />
            );

          case IOInputTypes.JSON:
            return (
              <IoJsonInput
                value={node.data.node!.template["input_value"]?.value}
                onChange={(e) => {
                  if (node) {
                    const newNode = cloneDeep(node);
                    newNode.data.node!.template["input_value"].value = e;
                    setNode(node.id, newNode);
                  }
                }}
                left={left}
              />
            );

          case IOInputTypes.STRING_LIST:
            return (
              <>
                <InputListComponent
                  id={`playground_${node.id}_input_list`}
                  editNode={false}
                  value={node.data.node!.template["input_value"]?.value}
                  handleOnNewValue={handleOnNewValue}
                  disabled={false}
                />
              </>
            );

          default:
            return (
              <Textarea
                className={`w-full custom-scroll ${
                  left ? "min-h-32" : "h-full"
                }`}
                placeholder={"Enter text..."}
                value={node.data.node!.template["input_value"]}
                onChange={(e) => {
                  e.target.value;
                  if (node) {
                    const newNode = cloneDeep(node);
                    newNode.data.node!.template["input_value"].value =
                      e.target.value;
                    setNode(node.id, newNode);
                  }
                }}
              />
            );
        }
      case InputOutput.OUTPUT:
        switch (fieldType) {
          case IOOutputTypes.TEXT:
            return <TextOutputView left={left} value={textOutputValue} />;
          case IOOutputTypes.PDF:
            return left ? (
              <div>{PDFViewConstant}</div>
            ) : (
              <PdfViewer pdf={agentPoolNode?.params ?? ""} />
            );
          case IOOutputTypes.CSV:
            return left ? (
              <>
                <CsvSelect
                  node={node}
                  handleChangeSelect={handleChangeSelect}
                />
              </>
            ) : (
              <>
                <CsvOutputComponent csvNode={node} agentPool={agentPoolNode} />
              </>
            );
          case IOOutputTypes.IMAGE:
            return left ? (
              <div>Expand the view to see the image</div>
            ) : (
              <ImageViewer
                image={
                  (agentPool[node.id] ?? [])[
                    (agentPool[node.id]?.length ?? 1) - 1
                  ]?.params ?? ""
                }
              />
            );

          case IOOutputTypes.JSON:
            return (
              <IoJsonInput
                value={node.data.node!.template["input_value"]?.value}
                onChange={(e) => {
                  if (node) {
                    const newNode = cloneDeep(node);
                    newNode.data.node!.template["input_value"].value = e;
                    setNode(node.id, newNode);
                  }
                }}
                left={left}
                output
              />
            );

          case IOOutputTypes.KEY_PAIR:
            return (
              <IOKeyPairInput
                value={node.data.node!.template["input_value"]?.value}
                onChange={(e) => {
                  if (node) {
                    const newNode = cloneDeep(node);
                    newNode.data.node!.template["input_value"].value = e;
                    setNode(node.id, newNode);
                  }
                  const valueToNumbers = convertValuesToNumbers(e);
                  setErrorDuplicateKey(hasDuplicateKeys(valueToNumbers));
                }}
                duplicateKey={errorDuplicateKey}
                isList={node.data.node!.template["input_value"]?.list ?? false}
              />
            );

          case IOOutputTypes.STRING_LIST:
            return (
              <>
                <InputListComponent
                  id={`playground_${node.id}_output_list`}
                  editNode={false}
                  value={node.data.node!.template["input_value"]?.value}
                  handleOnNewValue={handleOnNewValue}
                  disabled={true}
                />
              </>
            );
          case IOOutputTypes.DATA:
            return (
              <div className={left ? "h-56" : "h-full"}>
                <DataOutputComponent
                  pagination={!left}
                  rows={
                    Array.isArray(agentPoolNode?.data?.artifacts)
                      ? (agentPoolNode?.data?.artifacts?.map(
                          (artifact) => artifact.data,
                        ) ?? [])
                      : [agentPoolNode?.data?.artifacts]
                  }
                  columnMode="union"
                />
              </div>
            );

          default:
            return (
              <Textarea
                className={`w-full custom-scroll ${
                  left ? "min-h-32" : "h-full"
                }`}
                placeholder={"Empty"}
                // update to real value on agentPool
                value={
                  (agentPool[node.id] ?? [])[
                    (agentPool[node.id]?.length ?? 1) - 1
                  ]?.data.results.result ?? ""
                }
                readOnly
              />
            );
        }
      default:
        break;
    }
  }
  return handleOutputType();
}
