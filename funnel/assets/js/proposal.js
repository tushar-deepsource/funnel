export const Comments = {
  init(pageURL) {
    $('.comment .js-collapse').click(function() {
      $(this).addClass('mui--hide');
      $(this).siblings('.js-uncollapse').removeClass('mui--hide');
      $(this).parent().siblings('.comment--body').slideUp("fast");
      $(this).parent().siblings('.comment--children').slideUp("fast");
      return false;
    });

    $('.comment .js-uncollapse').click(function() {
      $(this).addClass('mui--hide');
      $(this).siblings('.js-collapse').removeClass('mui--hide');
      $(this).parent().siblings('.comment--body').slideDown("fast");
      $(this).parent().siblings('.comment--children').slideDown("fast");
      return false;
    });

    $('.comment .js-comment-reply').click(function() {
      var cfooter = $(this).parent();
      $('#comment-form input[name="parent_id"]').val(cfooter.attr('data-id'));
      $('#comment-form  input[name="comment_edit_id"]').val('');
      $("#toplevel-comment").removeClass('mui--hide');
      $("#comment-submit").val("Reply"); // i18n gotcha
      cfooter.after($("#comment-form"));
      $("#comment-form textarea").focus();
      return false;
    });

    $('#toplevel-comment a').click(function() {
      $('#comment-form  input[name="parent_id"]').val('');
      $('#comment-form  input[name="comment_edit_id"]').val('');
      $('#comment-submit').val("Post comment"); // i18n gotcha
      $(this).parent().after($('#comment-form'));
      $(this).parent().addClass('mui--hide');
      $('#comment-form textarea').focus();
      return false;
    });

    $('.comment .js-comment-delete').click(function() {
      var cfooter = $(this).parent();
      $('#delcomment input[name="comment_id"]').val(cfooter.attr('data-id'));
      $('#delcomment').attr('action', cfooter.attr('data-delete-url'))
      $('#delcomment').removeClass('mui--hide').hide().insertAfter(cfooter).slideDown("fast");
      return false;
    });

    $('#comment-delete-cancel').click(function() {
      $('#delcomment').slideUp('fast');
      return false;
    });

    $('.comment .js-comment-edit').click(function() {
      var cfooter = $(this).parent();
      var cid = cfooter.attr('data-id');
      $("#comment-form textarea").val("Loading..."); // i18n gotcha
      $.getJSON(pageURL+'/comments/'+cid+'/json', function(data) {
        $("#comment-form textarea").val(data.message);
      });
      $('#comment-form input[name="parent_id"]').val('');
      $('#comment-form input[name="comment_edit_id"]').val(cid);
      $('#toplevel-comment').removeClass('mui--hide');
      $('#comment-submit').val("Save changes"); // i18n gotcha
      cfooter.after($('#comment-form'));
      $('#comment-form textarea').focus();
      return false;
    });
  }
};

export const Video = {
  /* Takes argument
     `videoWrapper`: video container element,
     'videoUrl': video url
    Video id is extracted from the video url (extractYoutubeId).
    The videoID is then used to generate the iframe html.
    The generated iframe is added to the video container element.
  */
  getVideoTypeAndId(url) {
    let regexMatch = url.match(/(http:|https:|)\/\/(player.|www.)?(vimeo\.com|youtu(be\.com|\.be|be\.googleapis\.com))\/(video\/|embed\/|watch\?v=|v\/)?([A-Za-z0-9._%-]*)(&\S+)?/);
    let type = '';
    if (regexMatch[3].indexOf('youtu') > -1) {
      type = 'youtube';
    } else if (regexMatch[3].indexOf('vimeo') > -1) {
      type = 'vimeo';
    }
    return {
      type: type,
      videoId: regexMatch[6]
    };
  },
  embedIframe(videoWrapper, videoUrl) {
    let videoEmbedUrl;
    let {type, videoId} = this.getVideoTypeAndId(videoUrl);
    if(type === 'youtube') {
      videoEmbedUrl = `<iframe src='//www.youtube.com/embed/${videoId}' frameborder='0' allowfullscreen></iframe>`;
    } else if(type === 'vimeo') {
      videoEmbedUrl = `<iframe src='https://player.vimeo.com/video/${videoId}' frameborder='0' allowfullscreen></iframe>`;
    }
    videoWrapper.innerHTML = videoEmbedUrl;
  },
};

$(() => {
  window. HasGeek.ProposalInit = function ({pageUrl, videoWrapper= '', videoUrl= ''}) {
    Comments.init(pageUrl);

    if (videoWrapper) {
      Video.embedIframe(videoWrapper, videoUrl);
    }
  };
});
