import { useState } from "react";
import { X, Upload, File as FileIcon, Trash2 } from "lucide-react";
import { Button } from "@/components/ui/button";
import { Textarea } from "@/components/ui/textarea";
import { Label } from "@/components/ui/label";

interface ActionModalProps {
  open: boolean;
  setOpen: (open: boolean) => void;
  action: "approve" | "reject";
  entityType?: "agent" | "model" | "mcp";
  agentTitle: string;
  onSubmit: (data: { comments: string; attachments: File[] }) => Promise<void> | void;
  isLoading?: boolean;
}

export default function ActionModal({
  open,
  setOpen,
  action,
  entityType,
  agentTitle,
  onSubmit,
  isLoading = false,
}: ActionModalProps) {
  const [comments, setComments] = useState("");
  const [attachments, setAttachments] = useState<File[]>([]);
  const [error, setError] = useState("");
  const [isDragging, setIsDragging] = useState(false);

  const handleSubmit = async (e: React.FormEvent) => {
    e.preventDefault();
    const effectiveComments =
      action === "reject" && !comments.trim() && attachments.length === 0
        ? "Rejected by approver"
        : comments;

    if (!effectiveComments.trim() && attachments.length === 0) {
      setError("Please provide either comments or attachments");
      return;
    }

    try {
      await onSubmit({ comments: effectiveComments, attachments });
      handleClose();
    } catch (submitErr: any) {
      setError(submitErr?.message || "Failed to submit approval action");
    }
  };

  const handleClose = () => {
    setComments("");
    setAttachments([]);
    setError("");
    setIsDragging(false);
    setOpen(false);
  };

  const handleFileChange = (e: React.ChangeEvent<HTMLInputElement>) => {
    const files = Array.from(e.target.files || []);
    setAttachments([...attachments, ...files]);
    setError(""); // Clear error when files are added
  };

  const handleRemoveFile = (index: number) => {
    setAttachments(attachments.filter((_, i) => i !== index));
  };

  const formatFileSize = (bytes: number) => {
    if (bytes < 1024) return bytes + " B";
    if (bytes < 1024 * 1024) return (bytes / 1024).toFixed(2) + " KB";
    return (bytes / (1024 * 1024)).toFixed(2) + " MB";
  };

  // Drag and drop handlers - simplified approach
  const handleDragEnter = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    setIsDragging(true);
  };

  const handleDragLeave = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    
    // Check if we're leaving the drop zone container
    const rect = e.currentTarget.getBoundingClientRect();
    const x = e.clientX;
    const y = e.clientY;
    
    if (x <= rect.left || x >= rect.right || y <= rect.top || y >= rect.bottom) {
      setIsDragging(false);
    }
  };

  const handleDragOver = (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
  };

  const handleDrop = async (e: React.DragEvent<HTMLDivElement>) => {
    e.preventDefault();
    e.stopPropagation();
    
    console.log('Drop event triggered'); // Debug
    console.log('DataTransfer types:', e.dataTransfer.types); // Debug
    console.log('DataTransfer items:', e.dataTransfer.items); // Debug
    setIsDragging(false);

    try {
      // First, try to get files directly
      const droppedFiles = Array.from(e.dataTransfer.files);
      console.log('Dropped files:', droppedFiles); // Debug
      
      if (droppedFiles.length > 0) {
        setAttachments(prev => [...prev, ...droppedFiles]);
        setError("");
        return;
      }
      
      // If no files, check for Outlook-specific data
      const items = e.dataTransfer.items;
      
      if (items && items.length > 0) {
        const newFiles: File[] = [];
        
        for (let i = 0; i < items.length; i++) {
          const item = items[i];
          console.log('Item:', item.kind, item.type); // Debug
          
          // Handle Outlook's custom format
          if (item.type === 'multimaillistconversationrows' || 
              item.type.includes('outlook') ||
              item.type.includes('mail')) {
            
            await new Promise<void>((resolve) => {
              item.getAsString((data) => {
                console.log('Outlook data received, length:', data?.length);
                console.log('Data preview:', data?.substring(0, 200));
                
                if (data && data.length > 0) {
                  // Outlook sends email metadata/identifiers
                  // Create a placeholder file with this info
                  const timestamp = new Date().toISOString().slice(0, 19).replace(/:/g, '-');
                  const fileName = `Outlook_Email_${timestamp}.txt`;
                  
                  const content = `Outlook Email Dropped\n\nTimestamp: ${new Date().toLocaleString()}\n\nEmail Data:\n${data}`;
                  
                  const blob = new Blob([content], { type: 'text/plain' });
                  const file = new File([blob], fileName, { type: 'text/plain' });
                  
                  newFiles.push(file);
                  console.log('Created Outlook email file:', fileName);
                }
                resolve();
              });
            });
            continue;
          }
          
          // Check for FileSystemEntry (other virtual files)
          if (item.kind === 'file') {
            const entry = item.webkitGetAsEntry?.();
            
            if (entry && entry.isFile) {
              const file = item.getAsFile();
              if (file) {
                console.log('Got file from item:', file.name, file.type);
                newFiles.push(file);
              }
            }
          }
          
          // Try to get as string for email content
          if (item.type === 'text/plain' || item.type === 'text/html') {
            await new Promise<void>((resolve) => {
              item.getAsString((data) => {
                if (data && data.length > 100) {
                  console.log('Got email content, length:', data.length);
                  
                  const emailSubject = extractEmailSubject(data);
                  const fileName = emailSubject 
                    ? `${emailSubject}.txt` 
                    : `Email_${new Date().toISOString().slice(0, 19).replace(/:/g, '-')}.txt`;
                  
                  const blob = new Blob([data], { type: 'text/plain' });
                  const file = new File([blob], fileName, { type: 'text/plain' });
                  
                  newFiles.push(file);
                  console.log('Created email file:', fileName);
                }
                resolve();
              });
            });
          }
        }
        
        if (newFiles.length > 0) {
          setAttachments(prev => [...prev, ...newFiles]);
          setError("");
          console.log('Successfully added', newFiles.length, 'files');
          return;
        }
      }
      
      // If still nothing, show a helpful message
      console.warn('No files could be extracted from drop');
      setError("Unable to process the dropped Outlook email. Please try saving the email as .msg file first, then drag the file.");
      
    } catch (error) {
      console.error('Error handling drop:', error);
      setError("An error occurred while processing the dropped item.");
    }
  };

  // Helper function to extract email subject from HTML content
  const extractEmailSubject = (htmlOrText: string): string => {
    // Try to extract subject from HTML
    const subjectMatch = htmlOrText.match(/Subject:\s*(.+?)(?:\r?\n|<|$)/i);
    if (subjectMatch && subjectMatch[1]) {
      const subject = subjectMatch[1].trim().replace(/[<>:"/\\|?*]/g, '-');
      return subject.substring(0, 50); // Limit to 50 chars
    }
    
    // Try to extract from email headers in HTML
    const titleMatch = htmlOrText.match(/<title>(.+?)<\/title>/i);
    if (titleMatch && titleMatch[1]) {
      const subject = titleMatch[1].trim().replace(/[<>:"/\\|?*]/g, '-');
      return subject.substring(0, 50);
    }
    
    // Try to extract from first line
    const firstLine = htmlOrText.split('\n')[0].replace(/<[^>]*>/g, '').trim();
    if (firstLine && firstLine.length > 5 && firstLine.length < 100) {
      const subject = firstLine.replace(/[<>:"/\\|?*]/g, '-');
      return subject.substring(0, 50);
    }
    
    return '';
  };

  if (!open) return null;

  const isApprove = action === "approve";
  const entityLabel =
    entityType === "model" ? "Model" : entityType === "mcp" ? "MCP" : "Agent";

  return (
    <>
      {/* Backdrop with blur */}
      <div
        className="fixed inset-0 z-50 bg-background/80 backdrop-blur-sm"
        onClick={handleClose}
      />

      {/* Modal */}
      <div className="fixed left-[50%] top-[50%] z-50 w-full max-w-lg translate-x-[-50%] translate-y-[-50%] rounded-lg border border-border bg-card p-6 shadow-lg">
        {/* Header */}
        <div className="mb-6 flex items-start justify-between">
          <div>
            <h2 className="text-xl font-semibold text-card-foreground">
              {isApprove ? `Approve ${entityLabel}` : `Reject ${entityLabel}`}
            </h2>
            <p className="mt-1 text-sm text-muted-foreground">{agentTitle}</p>
          </div>
          <button
            onClick={handleClose}
            className="rounded-sm opacity-70 ring-offset-background transition-opacity hover:opacity-100"
          >
            <X className="h-5 w-5" />
            <span className="sr-only">Close</span>
          </button>
        </div>

        {/* Form */}
        <form onSubmit={handleSubmit} className="space-y-4">
          {/* Error Message */}
          {error && (
            <div className="rounded-md bg-destructive/10 p-3 text-sm text-destructive">
              {error}
            </div>
          )}

          {/* Comments */}
          <div className="space-y-2">
            <Label htmlFor="comments" className="text-sm font-medium">
              Comments
            </Label>
            <Textarea
              id="comments"
              value={comments}
              onChange={(e) => {
                setComments(e.target.value);
                setError(""); // Clear error when typing
              }}
              placeholder={
                isApprove
                  ? "Add optional feedback or notes..."
                  : "Please provide a reason for rejection..."
              }
              rows={5}
              className="resize-none bg-background"
            />
          </div>

          {/* File Attachments with Drag & Drop */}
          <div className="space-y-2">
            <Label htmlFor="attachments" className="text-sm font-medium">
              Attachments
            </Label>
            
            {/* Drag & Drop Zone */}
            <div
              onDragEnter={handleDragEnter}
              onDragOver={handleDragOver}
              onDragLeave={handleDragLeave}
              onDrop={handleDrop}
              onClick={() => document.getElementById("attachments")?.click()}
              className={`
                relative rounded-lg border-2 border-dashed p-6 text-center transition-all cursor-pointer
                ${
                  isDragging
                    ? "border-primary bg-primary/5 scale-[1.02]"
                    : "border-muted-foreground/25 hover:border-primary/50 hover:bg-accent/50"
                }
              `}
            >
              <input
                id="attachments"
                type="file"
                multiple
                onChange={handleFileChange}
                className="hidden"
                accept=".pdf,.doc,.docx,.txt,.png,.jpg,.jpeg,.xlsx,.csv,.msg,.eml"
              />
              
              <div className="flex flex-col items-center gap-2 pointer-events-none">
                <div className={`rounded-full p-3 ${isDragging ? "bg-primary/10" : "bg-muted"}`}>
                  <Upload className={`h-6 w-6 ${isDragging ? "text-primary" : "text-muted-foreground"}`} />
                </div>
                
                <div>
                  <p className="text-sm font-medium">
                    {isDragging ? "Drop files here" : "Drag & drop files here"}
                  </p>
                  <p className="text-xs text-muted-foreground mt-1">
                    or click to browse files
                  </p>
                </div>
                
                <p className="text-xs text-muted-foreground">
                  Supported: PDF, DOC, DOCX, TXT, PNG, JPG, XLSX, CSV, MSG, EML
                </p>
                <p className="text-xs text-muted-foreground mt-1">
                  You can also drag emails directly from Outlook
                </p>
              </div>
            </div>

            {/* File List */}
            {attachments.length > 0 && (
              <div className="mt-3 space-y-2">
                <p className="text-sm font-medium">
                  Uploaded Files ({attachments.length})
                </p>
                {attachments.map((file, index) => (
                  <div
                    key={index}
                    className="flex items-center justify-between rounded-md border border-border bg-muted/50 p-3"
                  >
                    <div className="flex items-center gap-3">
                      <FileIcon className="h-4 w-4 text-muted-foreground" />
                      <div className="flex flex-col">
                        <span className="text-sm font-medium">
                          {file.name}
                        </span>
                        <span className="text-xs text-muted-foreground">
                          {formatFileSize(file.size)}
                        </span>
                      </div>
                    </div>
                    <Button
                      type="button"
                      variant="ghost"
                      size="sm"
                      onClick={() => handleRemoveFile(index)}
                      className="h-8 w-8 p-0 hover:bg-destructive/10 hover:text-destructive"
                    >
                      <Trash2 className="h-4 w-4" />
                    </Button>
                  </div>
                ))}
              </div>
            )}

            <p className="text-xs text-muted-foreground">
              {isApprove
                ? "Either comments or attachments are required"
                : "Comments are optional for rejection (default reason will be used)"}
            </p>
          </div>

          {/* Action Buttons */}
          <div className="flex items-center gap-3 pt-4">
            <Button
              type="button"
              variant="outline"
              onClick={handleClose}
              className="flex-1"
            >
              Cancel
            </Button>
            <Button
              type="submit"
              variant={isApprove ? "default" : "destructive"}
              className="flex-1"
              disabled={isLoading}
            >
              {isLoading
                ? "Processing..."
                : isApprove
                  ? "Approve"
                  : "Reject"}
            </Button>
          </div>
        </form>
      </div>
    </>
  );
}
