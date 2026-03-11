import type { UseMutationResult } from "@tanstack/react-query";
import type { useMutationFunctionType } from "@/types/api";
import { api } from "../../api";
import { getURL } from "../../helpers/constants";
import { UseRequestProcessor } from "../../services/request-processor";

interface UploadAttachmentsParams {
  agentId: string;
  files: File[];
}

/**
 * Hook to upload attachments for an approval action
 * Uses FormData to handle file uploads
 */
export const useUploadApprovalAttachments: useMutationFunctionType<
  undefined,
  UploadAttachmentsParams
> = (options?) => {
  const { mutate, queryClient } = UseRequestProcessor();

  const uploadAttachmentsFn = async (
    params: UploadAttachmentsParams,
  ): Promise<void> => {
    const formData = new FormData();

    // Append each file to FormData
    params.files.forEach((file) => {
      formData.append("attachments", file);
    });

    await api.post(
      `${getURL("APPROVALS")}/${params.agentId}/attachments`,
      formData,
      {
        headers: {
          "Content-Type": "multipart/form-data",
        },
      },
    );
  };

  const mutation: UseMutationResult<
    void,
    any,
    UploadAttachmentsParams
  > = mutate(["useUploadApprovalAttachments"], uploadAttachmentsFn, {
    ...options,
  });

  return mutation;
};
